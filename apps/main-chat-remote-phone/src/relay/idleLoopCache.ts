export const IDLE_FILE_LIMIT = 16*1024*1024;
export const IDLE_CACHE_LIMIT = 128*1024*1024;
export const IDLE_RANGE_LIMIT = 24576;
export const IDLE_WRITE_LIMIT = 256*1024;
const hex = /^[a-f0-9]{64}$/;
export type IdleReadyEntry = {id:string;sha256:string;bytes:number;width:number;height:number;fps:number;frames:number;tags:string[];status:'ready'};
export type IdleUnavailableEntry = {id:string;tags:string[];status:'pending'|'unavailable';reason:string};
export type VideoQuality = {video_kbps:number;video_width:number;video_fps:number};
export type IdleSourceBinding = {motion_id:string;source_frame_count:number;avatar_id:string;loop_id:string};
export type IdleManifest = {version:1;generation:string;avatar:string;revision:string;active_loop:string|null;fade_ms:number;loops:(IdleReadyEntry|IdleUnavailableEntry)[];video_quality?:VideoQuality;active_source?:IdleSourceBinding|null;sources?:IdleSourceBinding[]};
export type VerifiedLoop = {id:string;generation:string;uri:string;sha256:string;bytes:number};
export type IdleCacheIO = {
  select(scope:string,avatarGeneration:string):Promise<string>;
  begin(generation:string,id:string,bytes:number,sha256:string):Promise<string>;
  append(handle:string,offset:number,chunk:Uint8Array):Promise<void>;
  finish(handle:string):Promise<VerifiedLoop>;
  abort(handle:string):Promise<void>;
  invalidate(generation:string):Promise<void>;
  get(generation:string,id:string):Promise<VerifiedLoop|null>;
  usage():Promise<{bytes:number;limit:number}>;
};
const object = (value:unknown): value is Record<string,any> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const keys = (value:Record<string,unknown>, names:string[]) => Object.keys(value).sort().join(',') === names.sort().join(',');
const integer = (v:unknown, low:number, high:number):v is number => Number.isSafeInteger(v) && Number(v)>=low && Number(v)<=high;
const identity = (v:unknown):v is string => typeof v==='string' && hex.test(v);

export function parseVideoQuality(value:unknown):VideoQuality {
  if(!object(value) || !keys(value,['video_kbps','video_width','video_fps'])
    || !integer(value.video_kbps,100,2000) || !integer(value.video_width,160,448)
    || value.video_width%2!==0 || ![6,8,12,24].includes(value.video_fps)) throw new Error('Invalid video quality.');
  return {video_kbps:value.video_kbps,video_width:value.video_width,video_fps:value.video_fps};
}

export function parseIdleManifest(value:unknown):IdleManifest {
  if (!object(value) || !keys(value,['version','generation','avatar','revision','active_loop','fade_ms','loops',
      ...('video_quality' in value?['video_quality']:[]),...('active_source' in value?['active_source']:[]),...('sources' in value?['sources']:[])])
      || value.version!==1 || !identity(value.generation) || !identity(value.avatar) || !identity(value.revision)
      || !integer(value.fade_ms,0,5000) || !Array.isArray(value.loops) || value.loops.length>128)
    throw new Error('Invalid idle manifest.');
  if('video_quality' in value)parseVideoQuality(value.video_quality);
  const ids=new Set<string>();
  for (const row of value.loops) {
    if (!object(row) || !identity(row.id) || ids.has(row.id) || !Array.isArray(row.tags) || row.tags.length>128
        || row.tags.some((tag:unknown)=>typeof tag!=='string' || tag.length>64 || /[\\/]/.test(tag))) throw new Error('Invalid idle entry.');
    ids.add(row.id);
    if (row.status==='ready') {
      if (!keys(row,['id','sha256','bytes','width','height','fps','frames','tags','status'])
          || !identity(row.sha256) || !integer(row.bytes,1,IDLE_FILE_LIMIT) || !integer(row.width,2,448)
          || !integer(row.height,2,672) || row.width%2!==0 || row.height%2!==0
          || ![6,8,12,24].includes(row.fps) || !integer(row.frames,1,1440)) throw new Error('Invalid idle video.');
    } else if (!keys(row,['id','tags','status','reason']) || !['pending','unavailable'].includes(row.status)
        || typeof row.reason!=='string' || !/^[a-z_]{1,64}$/.test(row.reason)) throw new Error('Invalid unavailable loop.');
  }
  if (value.active_loop!==null && (!identity(value.active_loop)
      || !value.loops.some((row:any)=>row.id===value.active_loop && row.status==='ready'))) throw new Error('Invalid active loop.');
  const validateSource=(source:any)=>{
    const row=value.loops.find((item:any)=>item.id===source?.loop_id);
    if(!object(source) || !keys(source,['motion_id','source_frame_count','avatar_id','loop_id'])
      || !identity(source.motion_id) || !integer(source.source_frame_count,1,1440)
      || typeof source.avatar_id!=='string' || source.avatar_id.length<1 || source.avatar_id.length>256
      || /[\\/\x00-\x1f]/.test(source.avatar_id) || !identity(source.loop_id)
      || !row || row.status!=='ready' || Math.ceil(source.source_frame_count*row.fps/24)!==row.frames)
      throw new Error('Invalid idle source binding.');
  };
  if(value.active_source!==undefined && value.active_source!==null) {
    validateSource(value.active_source);
    if(value.active_source.loop_id!==value.active_loop)throw new Error('Invalid active source binding.');
  }
  if(value.sources!==undefined){
    if(!Array.isArray(value.sources)||value.sources.length>128)throw new Error('Invalid idle sources.');
    const avatars=new Set<string>();
    for(const source of value.sources){
      validateSource(source);
      if(avatars.has(source.avatar_id))throw new Error('Duplicate idle source.');
      avatars.add(source.avatar_id);
    }
  }
  return JSON.parse(JSON.stringify(value)) as IdleManifest;
}

/** Owns only cache bytes. Native AV must separately validate presentation authority. */
export class IdleLoopCache {
  private epoch=0;
  private scope=''; private avatar=''; private generation='';
  private nativeGeneration='';
  private selecting:Promise<void>=Promise.resolve();
  private writing=false;
  private inventory:IdleManifest|null=null;
  private checked=new Map<string,VerifiedLoop>();
  constructor(private io:IdleCacheIO) {}
  setInventory(value:unknown):void {
    const manifest=parseIdleManifest(value);
    if(manifest.generation!==this.avatar || !this.generation) throw new Error('Idle inventory ownership ended.');
    this.inventory=manifest;
  }
  async select(scope:string,avatarGeneration:string):Promise<void> {
    if (!scope || scope.length>1024 || !identity(avatarGeneration)) throw new Error('Invalid idle scope.');
    if (scope===this.scope && avatarGeneration===this.avatar) return this.selecting;
    const epoch=++this.epoch;
    this.scope=scope; this.avatar=avatarGeneration; this.generation='';
    this.inventory=null;this.checked.clear();
    const previous=this.selecting;
    this.selecting=previous.catch(()=>undefined).then(()=>this.io.select(scope,avatarGeneration)).then(value=>{
      this.nativeGeneration=value;
      if(epoch===this.epoch) this.generation=value;
    }).catch(error=>{
      if(epoch===this.epoch) { this.scope=''; this.avatar=''; }
      throw error;
    });
    await this.selecting;
  }
  private live(epoch:number,signal?:AbortSignal) {
    if(epoch!==this.epoch || !this.generation || signal?.aborted) throw new Error('Idle cache work cancelled.');
  }
  private verified(value:VerifiedLoop, id:string) {
    if (!value || value.id!==id || value.generation!==this.generation || !identity(value.sha256)
        || !integer(value.bytes,1,IDLE_FILE_LIMIT) || typeof value.uri!=='string'
        || !value.uri.startsWith('file:') || !value.uri.endsWith(`/${id}.mp4`)) throw new Error('Invalid native idle file.');
    return value;
  }
  async get(id:string):Promise<VerifiedLoop|null> {
    if(!identity(id)) throw new Error('Invalid idle id.');
    const epoch=this.epoch; await this.selecting; this.live(epoch);
    const value=await this.io.get(this.generation,id); this.live(epoch);
    const verified=value ? this.verified(value,id) : null;
    if(verified) this.checked.set(id,verified);else this.checked.delete(id);
    return verified;
  }
  async put(entry:IdleReadyEntry,chunks:AsyncIterable<Uint8Array>,signal:AbortSignal):Promise<VerifiedLoop> {
    if (!identity(entry.id) || !identity(entry.sha256) || !integer(entry.bytes,1,IDLE_FILE_LIMIT) || entry.status!=='ready') throw new Error('Invalid idle entry.');
    const epoch=this.epoch; await this.selecting; this.live(epoch,signal);
    if(this.writing) throw new Error('Idle cache writer busy.');
    this.writing=true;
    let handle='';
    try {
      const existing=await this.get(entry.id); this.live(epoch,signal);
      if(existing && existing.sha256===entry.sha256 && existing.bytes===entry.bytes) return existing;
      const usage=await this.io.usage(); this.live(epoch,signal);
      if(usage.bytes+entry.bytes>IDLE_CACHE_LIMIT) throw new Error('Idle storage limited.');
      handle=await this.io.begin(this.generation,entry.id,entry.bytes,entry.sha256); this.live(epoch,signal);
      let offset=0;
      for await(const chunk of chunks) {
        this.live(epoch,signal);
        if(!ArrayBuffer.isView(chunk) || chunk.byteLength<1 || chunk.byteLength>IDLE_WRITE_LIMIT || offset+chunk.byteLength>entry.bytes) throw new Error('Invalid idle chunk.');
        await this.io.append(handle,offset,chunk); offset+=chunk.byteLength;
      }
      this.live(epoch,signal);
      if(offset!==entry.bytes) throw new Error('Incomplete idle loop.');
      const value=await this.io.finish(handle); this.live(epoch,signal);
      const verified=this.verified(value,entry.id);
      if(verified.bytes!==entry.bytes || verified.sha256!==entry.sha256) throw new Error('Idle integrity failure.');
      this.checked.set(entry.id,verified);
      return verified;
    } finally {
      if(handle) await this.io.abort(handle).catch(()=>undefined);
      this.writing=false;
    }
  }
  async clear():Promise<void> {
    const epoch=++this.epoch, previous=this.selecting;
    this.generation='';
    this.inventory=null;this.checked.clear();
    const scope=this.scope, avatar=this.avatar;
    this.selecting=(async()=>{
      await previous.catch(()=>undefined);
      // A fresh process can still have persisted files, before any peer selects
      // an inventory. Select a disposable owner to purge only this cache root.
      const target=this.nativeGeneration || await this.io.select('manual-clear','0'.repeat(64));
      await this.io.invalidate(target);
      this.nativeGeneration='';
      if(scope && avatar && epoch===this.epoch) {
        const value=await this.io.select(scope,avatar);
        this.nativeGeneration=value;
        if(epoch===this.epoch) this.generation=value;
      }
    })();
    await this.selecting;
  }
  async usage():Promise<{bytes:number;limit:number;complete:boolean;reason:string;files:number;requiredBytes:number}> {
    const epoch=this.epoch;
    const result=await this.io.usage();
    if(epoch!==this.epoch) throw new Error('Idle usage ownership ended.');
    const entries=this.inventory?.loops ?? [];
    let files=0,requiredBytes=0;
    for(const entry of entries) if(entry.status==='ready') {
      requiredBytes+=entry.bytes;
      const checked=this.checked.get(entry.id);
      if(checked?.generation===this.generation && checked.sha256===entry.sha256 && checked.bytes===entry.bytes) files++;
    }
    const complete=Boolean(this.inventory) && files===entries.length && !this.writing;
    return {...result,complete,files,requiredBytes,reason:this.writing?'downloading':complete?'ready'
      :!this.inventory?'inventory_not_checked':entries.some(row=>row.status!=='ready')?'incomplete_inventory':'download_pending'};
  }
}
