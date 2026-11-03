import {IdleLoopCache,parseIdleManifest} from './idleLoopCache';
import type {IdleManifest,VerifiedLoop} from './idleLoopCache';
import {IdleLoopTransfer} from './idleLoopTransfer';
import type {IdleRange} from './idleLoopTransfer';

type Client={readonly idleCacheScope:string;idleCacheRange(range:IdleRange,signal:AbortSignal):Promise<Uint8Array>};
export type IdlePresentation={readonly nativeHandle:string;readonly idleSupported:boolean;readonly idleBusy:boolean;
  idleQualityMatches?(manifest:IdleManifest):boolean;
  prepareIdle(file:VerifiedLoop,manifest:IdleManifest):Promise<boolean>;
  selectIdle(file:VerifiedLoop,manifest:IdleManifest):Promise<boolean>;
  clearIdle():void|Promise<void>;acknowledgeIdle(manifest:IdleManifest,ready:boolean):Promise<void>};
export type IdleSessionStatus={complete:boolean;reason:string;files:number;bytes:number;requiredBytes:number;failureStage?:string};

class IdleStageFailure extends Error {constructor(readonly stage:string){super('Idle cache operation failed');}}
async function atStage<T>(stage:string,work:()=>Promise<T>):Promise<T>{
  try{return await work();}catch{throw new IdleStageFailure(stage);}
}

/** Bytes persist across reconnect, but decoded readiness belongs to one native
 * handle. Neither file presence nor this coordinator can acknowledge speech. */
export class IdleLoopSession {
  status:IdleSessionStatus={complete:false,reason:'inventory_pending',files:0,bytes:0,requiredBytes:0};
  private work:Promise<void>=Promise.resolve();
  private abort:AbortController|null=null;
  private renew:(()=>Promise<void>)|null=null;
  private renewing=false;
  private clearing=false;
  private detached:Promise<void>=Promise.resolve();
  private detachVisual(){
    // Hide immediately; fence every retiring native reader before cache IO.
    let fence:Promise<void>;
    try{fence=Promise.resolve(this.output.clearIdle());}catch(error){fence=Promise.reject(error);}
    this.detached=Promise.all([this.detached,fence]).then(()=>undefined);
    void this.detached.catch(()=>undefined);
  }
  private key='';private selection='';private presented='';private epoch=0;
  constructor(private client:Client,private output:IdlePresentation,private cache:IdleLoopCache) {}
  settled(){return this.work;}
  async update(value:unknown,clearGeneration=0):Promise<void>{
    if(this.clearing)return;
    const manifest=parseIdleManifest(value),scope=this.client.idleCacheScope,handle=this.output.nativeHandle;
    if(!scope || !handle || !this.output.idleSupported){this.pause();this.status.reason='native_update_required';return;}
    // The inventory describes the producer, which may be several chunks ahead.
    // Keep the current reader/source until the presentation retires its handoff.
    // The next ordinary poll applies the latest inventory; no stale update queue.
    if(this.output.idleBusy){this.status.reason='playback_active';return;}
    if(manifest.video_quality && !this.output.idleQualityMatches?.(manifest)){
      this.pause();this.status.reason='quality_reconnect_required';return;
    }
    const storageScope=JSON.stringify([scope,clearGeneration]);
    const selection=JSON.stringify([storageScope,manifest.generation]);
    const key=JSON.stringify([selection,handle,manifest.revision,manifest.active_loop,manifest.active_source]);
    if(key===this.key && this.abort) {
      if(this.renew && !this.renewing){this.renewing=true;try{await this.renew();}finally{this.renewing=false;}}
      return;
    }
    this.abort?.abort();const controller=new AbortController(),epoch=++this.epoch;
    this.abort=controller;this.key=key;this.renew=null;
    if(selection!==this.selection){this.detachVisual();this.presented='';this.selection=selection;}
    const live=()=>!controller.signal.aborted && epoch===this.epoch && this.client.idleCacheScope===scope
      && this.output.nativeHandle===handle;
    this.work=this.work.catch(()=>undefined).then(async()=>{
      if(!live()) return;
      await atStage('native_detach',()=>this.detached);if(!live())return;
      await atStage('storage_select',()=>this.cache.select(storageScope,manifest.generation));if(!live()) return;
      this.cache.setInventory(manifest);
      const show=async()=>{
        if(!live() || this.output.idleBusy) return;
        const file=manifest.active_loop?await atStage('storage_read',()=>this.cache.get(manifest.active_loop!)):null;if(!live())return;
        if(this.output.idleBusy)return;
        const acknowledge=(ready:boolean)=>atStage('ready_ack',()=>this.output.acknowledgeIdle(manifest,ready));
        if(!file){this.detachVisual();this.presented='';await acknowledge(false);return;}
        const identity=JSON.stringify([handle,file.generation,file.id,file.sha256,manifest.active_source?.source_frame_count]);
        if(identity!==this.presented){
          const decoded=await atStage('native_prepare',()=>this.output.prepareIdle(file,manifest));if(!live())return;
          if(!decoded){await acknowledge(false);return;}
        }
        // Recheck the actual native player after eviction/decoder failure.
        // Selecting its current identity is a no-op (no restart or fade).
        const selected=await atStage('native_select',()=>this.output.selectIdle(file,manifest));if(!live())return;
        if(!selected){this.presented='';await acknowledge(false);return;}
        this.presented=identity;
        await acknowledge(true);
      };
      await show();if(!live())return;
      this.renew=async()=>{
        // Renew the decoded-loop lease even while later mood files download.
        // Never race a still-pending prepare/select for the first file.
        if(this.presented)await show();
        if(live())this.status={...await atStage('storage_usage',()=>this.cache.usage())};
      };
      this.status={...await atStage('storage_usage',()=>this.cache.usage())};
      const transfer=new IdleLoopTransfer(this.cache,(range,signal)=>this.client.idleCacheRange(range,signal),
        ()=>this.output.idleBusy,undefined,async entry=>{
          if(entry.id===manifest.active_loop)await show();
          if(live())this.status={...await atStage('storage_usage',()=>this.cache.usage())};
        });
      const result=await transfer.sync(manifest,controller.signal);if(!live())return;
      const usage=await atStage('storage_usage',()=>this.cache.usage());if(!live())return;
      this.status={...result,bytes:usage.bytes};
      if(!this.presented)this.status.reason='decoder_pending';
    }).catch(error=>{
      if(live())this.status={...this.status,complete:false,reason:'streamed_fallback',
        failureStage:error instanceof IdleStageFailure?error.stage:'transfer'};
    }).finally(()=>{if(epoch===this.epoch)this.abort=null;});
  }
  pause(){++this.epoch;this.abort?.abort();this.abort=null;this.renew=null;this.key='';this.presented='';this.detachVisual();
    this.status={...this.status,complete:false,reason:'paused'};}
  async clear(){this.clearing=true;this.pause();try{await this.work;await this.detached;await this.cache.clear();
    this.status={complete:false,reason:'cleared',files:0,bytes:0,requiredBytes:0};}finally{this.clearing=false;}}
}
