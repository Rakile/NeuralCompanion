import type {OrderedIdleInventory} from './orderedIdleInventory';
import type {OrderedCachePolicy} from './orderedChunkStore';
import type {OrderedRun,OrderedFrame} from './desktopOrderedProtocol';

type Frontier=Readonly<{version:1;streamId:string;generation:number;nextOrdinal:number;revision:number;
  replyId:string|null;lastFrame:OrderedFrame|null}>;
export type CachedIdleCandidate=Readonly<{streamId:string;generation:number;loopId:string;motionId:string;
  inventoryRevision:string;cacheEpoch:number;sourceFrameCount:number;entryFrame:number;afterOrdinal:number;
  afterFrameCount:number;fadeMs:number}>;
type Grant=CachedIdleCandidate&Readonly<{version:1;activationRevision:number;fps:24}>;
type Observation=Readonly<{activationRevision:number;streamId:string;generation:number;loopId:string;sourceFrame:number;ageMs:number}>;
type Native=Record<string,(request:string)=>Promise<unknown>>;
export type CachedIdleStall=Readonly<{stage:string;waitingMs:number;prepareMs:number|null;prepareAttempts:number;
  frontierMisses:number;tailMisses:number;afterOrdinal:number|null;sourceFrame:number|null;
  sourceFrameCount:number|null;sourceId:string|null;activationRevision:number|null}>;
type Dependencies={inventory:Pick<OrderedIdleInventory,'find'>;policy():OrderedCachePolicy;
  session():Readonly<{run:OrderedRun;streamId:string;generation:number}>|null;current():boolean;
  native:Native;call(request:Record<string,unknown>):Promise<unknown>;now?():number;
  onRecovery?(reason:string):void;onDiagnostic?(value:CachedIdleStall):void;onFailure(error:unknown):void};
const int=(n:unknown,min=0,max=Number.MAX_SAFE_INTEGER):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=min&&n<=max;
const hex=(s:unknown,size=64):s is string=>typeof s==='string'&&s.length===size&&/^[a-f0-9]+$/.test(s);
function row(value:unknown,keys:readonly string[],site:string):Record<string,unknown>{
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==keys.length
    ||!keys.every(key=>Object.prototype.hasOwnProperty.call(value,key)))throw Error('ordered.cached_'+site+'_fields');
  return value as Record<string,unknown>;
}
function frontier(value:unknown):Frontier{
  const r=row(value,['version','streamId','generation','nextOrdinal','revision','replyId','lastFrame'],'frontier');
  if(r.version!==1||!hex(r.streamId,32)||!int(r.generation)||!int(r.nextOrdinal)||!int(r.revision)
    ||r.replyId!==null&&(typeof r.replyId!=='string'||!/^[A-Za-z0-9_-]{1,128}$/.test(r.replyId)))throw Error('ordered.cached_frontier');
  if(r.lastFrame!==null){const f=row(r.lastFrame,['sourceId','frame','sourceFrameCount'],'frame');
    if(typeof f.sourceId!=='string'||!/^[A-Za-z0-9_-]{1,160}$/.test(f.sourceId)
      ||!int(f.sourceFrameCount,1)||!int(f.frame,0,f.sourceFrameCount-1))throw Error('ordered.cached_frame');}
  return r as unknown as Frontier;
}
const candidateKeys=['streamId','generation','loopId','motionId','inventoryRevision','cacheEpoch','sourceFrameCount',
  'entryFrame','afterOrdinal','afterFrameCount','fadeMs'] as const;
function grant(value:unknown):Grant{
  const r=row(value,['version','activationRevision','fps',...candidateKeys],'grant');
  if(r.version!==1||r.fps!==24||!int(r.activationRevision,1)||!hex(r.streamId,32)||!int(r.generation)
    ||!hex(r.loopId)||!hex(r.motionId)||!hex(r.inventoryRevision)||!int(r.cacheEpoch)
    ||!int(r.sourceFrameCount,1,1440)||!int(r.entryFrame,0,r.sourceFrameCount-1)
    ||!int(r.afterOrdinal)||!int(r.afterFrameCount,1,12)||!int(r.fadeMs,0,5000))throw Error('ordered.cached_grant');
  return Object.freeze({...r}) as unknown as Grant;
}
function candidate(value:Grant):CachedIdleCandidate{
  return Object.freeze(Object.fromEntries(candidateKeys.map(key=>[key,value[key]]))) as CachedIdleCandidate;
}
function observation(value:unknown,g:Grant):Observation{
  const r=row(value,['activationRevision','streamId','generation','loopId','sourceFrame','ageMs'],'observation');
  if(r.activationRevision!==g.activationRevision||r.streamId!==g.streamId||r.generation!==g.generation||r.loopId!==g.loopId
    ||!int(r.sourceFrame,0,g.sourceFrameCount-1)||!int(r.ageMs,0,250))throw Error('ordered.cached_observation_scope');
  return Object.freeze({...r}) as unknown as Observation;
}

/** Independent visual-control worker. File acquisition and the continuous
 * speech pump never wait for it. No repeated idle ordinals, audio receipts,
 * synthetic tail completion or reader-closure flags are produced here. */
export class OrderedCachedIdle {
  private work?:Promise<void>;private pausing?:Promise<void>;private closing?:Promise<void>;
  private closed=false;private epoch=0;private held:Grant|null=null;private acknowledged=0;private nextCheck=0;
  private retryAt=0;
  private nativePreparationAttempted=false;
  private waitStarted:number|null=null;private diagnosticStage='waiting_boundary';
  private readonly reportedStages=new Set<string>();
  private readonly reportedRecoveries=new Set<string>();
  private prepareAttempts=0;private frontierMisses=0;private tailMisses=0;private prepareMs:number|null=null;
  private target:CachedIdleCandidate|null=null;
  private observedFrontier:Frontier|null=null;
  constructor(private readonly deps:Dependencies){}
  private current(epoch:number){return !this.closed&&!this.pausing&&epoch===this.epoch&&this.deps.current();}
  private now(){return this.deps.now?.()??Date.now();}
  private stage(value:string){
    if(this.waitStarted===null)this.waitStarted=this.now();
    this.diagnosticStage=value;
  }
  private resetDiagnostic(){
    this.waitStarted=null;this.reportedStages.clear();this.target=null;this.observedFrontier=null;
    this.prepareAttempts=this.frontierMisses=this.tailMisses=0;this.prepareMs=null;
  }
  private reportStall(){
    if(!this.deps.onDiagnostic||this.waitStarted===null||this.now()-this.waitStarted<5000
      ||this.reportedStages.has(this.diagnosticStage))return;
    this.reportedStages.add(this.diagnosticStage);
    const target=this.target,frontier=this.observedFrontier,frame=frontier?.lastFrame;
    try{this.deps.onDiagnostic(Object.freeze({stage:this.diagnosticStage,waitingMs:this.now()-this.waitStarted,
      prepareMs:this.prepareMs,prepareAttempts:this.prepareAttempts,frontierMisses:this.frontierMisses,tailMisses:this.tailMisses,
      afterOrdinal:target?.afterOrdinal??(frontier&&frontier.nextOrdinal>0?frontier.nextOrdinal-1:null),
      sourceFrame:target?.entryFrame??(frame?(frame.frame+1)%frame.sourceFrameCount:null),
      sourceFrameCount:target?.sourceFrameCount??frame?.sourceFrameCount??null,sourceId:target?.motionId??frame?.sourceId??null,
      activationRevision:this.held?.activationRevision??null}));}catch{} // Never changes playback authority.
  }
  private async native(method:string,run:OrderedRun|null,body:Record<string,unknown>={}){
    const fn=this.deps.native[method];if(typeof fn!=='function')throw Error('ordered.cached_native_unavailable');
    return fn.call(this.deps.native,JSON.stringify({version:1,run,...body}));
  }
  tick():Promise<void>{
    if(!this.closed&&!this.pausing&&this.deps.current())this.reportStall();
    if(this.work)return this.work;
    if(this.closed||this.pausing||!this.deps.current()||this.deps.policy().mode!=='on'||this.now()<this.retryAt)return Promise.resolve();
    const scope=this.deps.session();if(!scope)return Promise.resolve();
    const epoch=this.epoch;
    return this.work=this.step(epoch,scope).catch(error=>{
      if(!this.current(epoch))return;
      if((error as Error)?.message==='ordered_cached_return_pending'){
        this.stage('waiting_return');this.nextCheck=0;return;
      }
      if(['output_frontier_changed','ordered_cached_tail_unretained'].includes((error as Error)?.message)){
        // Preparation raced normal streamed progress/reader reclamation. No
        // grant was issued: leave that output running and retry its new frontier.
        if((error as Error).message==='output_frontier_changed')this.frontierMisses++;else this.tailMisses++;
        this.stage('reserve_retry');this.nextCheck=0;return;
      }
      const reason=(error as Error)?.message;
      if(reason==='ordered_cached_inventory'||reason==='ordered_cached_inventory_pending'
        ||/^ordered\.cached_renderer_(decode|presentation_timeout|renderer)$/.test(reason??'')){
        this.retryAt=this.now()+1000;
        if(!this.reportedRecoveries.has(reason)){
          this.reportedRecoveries.add(reason);try{this.deps.onRecovery?.(reason);}catch{}
        }
        // Do not await our own worker here. It settles first, then exact grant
        // revocation and native reader join restore the ordinary streamed lane.
        void this.pause().catch(failure=>this.deps.onFailure(failure));return;
      }
      this.deps.onFailure(error);
    }).finally(()=>{this.work=undefined;});
  }
  private async step(epoch:number,scope:NonNullable<ReturnType<Dependencies['session']>>){
    if(this.held){
      const status=row(await this.native('ncReadOrderedCached',scope.run,{activationRevision:this.held.activationRevision}),['version','activation','position','failure'],'native_status');
      if(!this.current(epoch))return;
      if(status.version!==1)throw Error('ordered.cached_native_version');
      if(status.failure!==null){
        if(typeof status.failure!=='string'||!['decode','presentation_timeout','renderer'].includes(status.failure))throw Error('ordered.cached_native_failure');
        throw Error('ordered.cached_renderer_'+status.failure);
      }
      if(status.activation!==null){
        const observed=observation(status.activation,this.held);
        if(observed.sourceFrame!==this.held.entryFrame)throw Error('ordered.cached_activation_entry');
        if(this.acknowledged!==this.held.activationRevision){
          const ack=grant(await this.deps.call({action:'activate',observed}));
          if(!this.current(epoch))return;
          if(['version','fps','activationRevision',...candidateKeys].some(key=>ack[key as keyof Grant]!==this.held![key as keyof Grant]))
            throw Error('ordered.cached_activation_ack');
          this.acknowledged=ack.activationRevision;
          this.reportedRecoveries.clear();
          this.resetDiagnostic();
        }
      }else this.stage('activation_pending');
    }
    if(this.now()<this.nextCheck)return;
    this.nextCheck=this.now()+(this.acknowledged?1000:250);
    const state=row(await this.deps.call({action:'state'}),['version','frontier','grant','active'],'state');
    if(!this.current(epoch))return;
    if(state.version!==1||typeof state.active!=='boolean')throw Error('ordered.cached_state');
    const expected=frontier(state.frontier);
    if(expected.streamId!==scope.streamId||expected.generation!==scope.generation)throw Error('ordered.cached_state_scope');
    this.observedFrontier=expected;
    if(expected.replyId!==null){this.resetDiagnostic();return;}
    if(!expected.lastFrame||expected.nextOrdinal===0){this.stage('waiting_boundary');return;}
    const existing=state.grant===null?null:grant(state.grant);
    if(existing&&this.held?.activationRevision===existing.activationRevision&&existing.afterOrdinal===expected.nextOrdinal-1)return;
    const ready=this.deps.inventory.find(expected.lastFrame.sourceId);
    if(!ready){this.stage('waiting_inventory');return;}
    if(this.diagnosticStage==='waiting_inventory')this.resetDiagnostic();
    if(ready.binding.source_frame_count!==expected.lastFrame.sourceFrameCount||ready.entry.frames!==expected.lastFrame.sourceFrameCount)
      throw Error('ordered.cached_ready_binding');
    const policy=this.deps.policy();if(policy.mode!=='on')return;
    // Native's own queue validates the tail's actual frame count at activation.
    // Desktop returns that exact count in its state reservation, including tails.
    const proposed:CachedIdleCandidate={streamId:scope.streamId,generation:scope.generation,loopId:ready.entry.id,
      motionId:ready.binding.motion_id,inventoryRevision:ready.manifest.revision,cacheEpoch:policy.epoch,
      sourceFrameCount:ready.binding.source_frame_count,entryFrame:(expected.lastFrame.frame+1)%ready.binding.source_frame_count,
      afterOrdinal:expected.nextOrdinal-1,afterFrameCount:existing?.afterOrdinal===expected.nextOrdinal-1?existing.afterFrameCount:12,
      fadeMs:ready.manifest.fade_ms};
    // Desktop atomically pins its actual published tail before asynchronous
    // native preparation. Existing queued idle keeps playing; a moving frontier
    // cannot invalidate a prepared picture on every half-second publication.
    this.target=proposed;this.stage('reserving');
    const reserved=grant(await this.deps.call({action:'reserve_current',
      asset:{cacheEpoch:policy.epoch,inventoryRevision:ready.manifest.revision,loopId:ready.entry.id,
        motionId:ready.binding.motion_id,sourceFrameCount:ready.binding.source_frame_count}}));
    for(const key of ['streamId','generation','loopId','motionId','inventoryRevision','cacheEpoch','sourceFrameCount'] as const)
      if(reserved[key]!==proposed[key])throw Error('ordered.cached_reservation_ack');
    if(reserved.afterOrdinal<proposed.afterOrdinal)throw Error('ordered.cached_reservation_ack');
    this.held=reserved;this.acknowledged=0;this.target=candidate(reserved);
    // Even a cancelled worker owns cleanup of its authenticated returned grant.
    // pause waits for this worker before revoking exactly that revision.
    if(!this.current(epoch))return;
    this.stage('preparing');this.prepareAttempts++;
    const prepareStarted=this.now();
    this.nativePreparationAttempted=true;
    const prepared=await this.native('ncPrepareOrderedCached',scope.run,{candidate:candidate(reserved),
      file:{uri:ready.file.uri,sha256:ready.file.sha256,bytes:ready.file.bytes}});
    this.prepareMs=this.now()-prepareStarted;
    if(prepared!==true){
      this.stage('prepare_declined');this.retryAt=this.now()+1000;
      // Release this exact reservation after the worker settles. Never await
      // our own worker or leave streamed idle suppressed by declined setup.
      void this.pause().catch(failure=>this.deps.onFailure(failure));return;
    }
    if(!this.current(epoch))return;
    if(await this.native('ncArmOrderedCached',scope.run,{candidate:candidate(reserved),activationRevision:reserved.activationRevision})!==true)
      throw Error('ordered.cached_arm_rejected');
    this.stage('activation_pending');
  }
  pause():Promise<void>{
    // Inventory shutdown can pause again after terminal cleanup released the
    // shared player. Reuse settlement, including rejection, without another RPC.
    if(this.closed&&this.closing)return this.closing;
    if(this.pausing)return this.pausing;
    this.epoch++;
    return this.pausing=(async()=>{
      await this.work;
      const scope=this.deps.session();
      // Before an ordered open there cannot be a cached decoder: preparation
      // requires that run. Do not send run:null to the strict native parser.
      if(!scope&&this.nativePreparationAttempted)throw Error('ordered.cached_cleanup_run_missing');
      // Exact grant revocation only; disconnect cleanup is owned by the stream.
      if(this.held&&this.deps.current())await this.deps.call({action:'revoke',activationRevision:this.held.activationRevision});
      if(scope&&await this.native('ncCloseOrderedCached',scope.run)!==true)throw Error('ordered.cached_reader_join_unconfirmed');
      this.nativePreparationAttempted=false;
      this.held=null;this.acknowledged=0;this.nextCheck=0;
      this.resetDiagnostic();
    })().finally(()=>{this.pausing=undefined;});
  }
  close():Promise<void>{this.closed=true;return this.closing??=this.pause();}
}
