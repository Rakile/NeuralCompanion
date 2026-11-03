import type {AudioChunk} from '../api/types';
import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import type {BufferedMediaStore,BufferedMediaLease,BufferedMediaDescriptor} from '../relay/bufferedMedia';
import {parseLiveStatus,parseAnticipationStatus} from './museTalkLiveTrial';
import {parseSourceTimeline} from '../relay/frameHandoff';
import type {SourceTimeline} from '../relay/frameHandoff';
import type {IdleChunkReturn} from './idleChunkProtocol';
import type {ContinuousDescriptor} from './muxedContinuousProtocol';
import {PlanTransactionTrace} from '../diagnostics/planTransaction';

export type MuxedTrialPlan={mediaId:string;timeline:SourceTimeline;idleReturn:IdleChunkReturn;loopFadeMs:number;
  anticipation?:{planId:string;mediaId:string;avatarId:string;sourceFrameCount:number;sourceIndices:number[];
    speechEntryFrame:number;exitAfterFrame:number;repeat:boolean}};

export type MuxedTrialFile={uri:string;bytes:number;index:number;startFrame:number;frameCount:number;
  validSamples:number;delaySamples:number;paddingSamples:number;rawSamples:number;sampleRate:48000;fps:24};
export type MuxedRangePreparation={sequence_index:number;range_index:number;start_frame:number;frame_count:number;
  producer_work_ms:number;source_ready_ms:number;published_ms:number;retain_ms:number};
export type MuxedSourceTotals={frameCount:number;samples:number;rangeCount:number};
type Dependencies={trialId:string;store:Pick<BufferedMediaStore,'acquire'|'owns'>;
  independent?:boolean;limits?:{maxFiles:number;maxBytes:number};readyWait?:boolean;
  authority(chunk:AudioChunk):BufferedReplyAuthority|null;
  retryable?(error:unknown):boolean;
  onRangeRetained?(details:MuxedRangePreparation):void|Promise<void>;
  onWaitingPlan?(chunk:AudioChunk,plan:NonNullable<MuxedTrialPlan['anticipation']>,signal:AbortSignal):Promise<void>;
  request(method:'GET'|'POST',path:string,body?:Record<string,unknown>,signal?:AbortSignal,diagnosticLink?:import('../diagnostics/planTransaction').DiagnosticLink):Promise<unknown>};
type RecordEntry={chunk:AudioChunk;authority:BufferedReplyAuthority;identity:string;abort:AbortController;
  leases:Map<number,BufferedMediaLease>;files:Map<number,MuxedTrialFile>;anticipationFiles:Map<number,MuxedTrialFile>;work:Promise<void>;readers:number;
  changes:Set<()=>void>;done:boolean;failure?:{error:unknown};totals?:MuxedSourceTotals;
  unconfirmed?:{error:unknown};
  source?:string;timeline?:string;plan?:string;waiting?:string;native?:()=>Promise<void>;detaching?:Promise<void>;releasing?:Promise<void>};
const PREFIX='/api/dev/musetalk-live/';
const identity=(a:BufferedReplyAuthority)=>JSON.stringify([a.scope.owner,a.scope.replyId,a.scope.expiresAt,a.ticket,a.auth]);
const duration=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)&&value>=0?Math.min(value,120000):-1;

/** Opt-in delivery only: the native guarded player owns output/receipts. No
 * separate audio file/player, heard acknowledgement or second avatar plan.
 * The default path retains a complete bounded source. Independent streaming
 * exposes only its retained contiguous prefix to native playlist admission.
 */
export class MuxedTrialDelivery {
  private readonly records=new Map<string,RecordEntry>();
  private closed=false;
  private closing:Promise<void>|null=null;
  private quiescing:Promise<void>|null=null;
  private previous:Promise<void>=Promise.resolve();
  private reservedFiles=0;
  private reservedBytes=0;
  private reservationTail:Promise<void>=Promise.resolve();
  private readonly readyWaitEnabled:boolean;
  private readonly diagnostics:PlanTransactionTrace;
  constructor(private readonly deps:Dependencies) {
    this.diagnostics=new PlanTransactionTrace(deps.trialId);
    this.readyWaitEnabled=Boolean(deps.readyWait);
    if(!/^[a-f0-9]{32}$/.test(deps.trialId))throw Error('Invalid muxed trial.');
    if(deps.limits&&(!Number.isSafeInteger(deps.limits.maxFiles)||deps.limits.maxFiles<1
      ||!Number.isSafeInteger(deps.limits.maxBytes)||deps.limits.maxBytes<1))throw Error('Invalid muxed delivery limits.');
  }
  private check(row:RecordEntry) {
    if(row.failure)throw row.failure.error;
    const now=this.deps.authority(row.chunk);
    if(this.closed||row.abort.signal.aborted||!now||identity(now)!==row.identity
      ||now.scope.expiresAt<=Date.now())throw Error('Muxed reply authority ended.');
  }
  private record(chunk:AudioChunk):RecordEntry {
    const authority=this.deps.authority(chunk);
    if(this.closed||!authority||!authority.ticket||!authority.scope.owner
      ||authority.scope.replyId!==chunk.phone_request_id||authority.scope.expiresAt<=Date.now()
      ||!/^[A-Za-z0-9_.-]{1,128}$/.test(chunk.id)||chunk.url_path!==`/api/audio/file/${chunk.id}`
      ||!Number.isSafeInteger(chunk.sequence_index)||chunk.sequence_index!<0||chunk.sequence_index!>=64)
      throw Error('Invalid muxed reply authority.');
    const prior=this.records.get(chunk.id);
    if(prior){this.check(prior);if(prior.chunk.sequence_index!==chunk.sequence_index)throw Error('Muxed source changed.');return prior;}
    if(this.records.size>=64)throw Error('Muxed source capacity reached.');
    const row:RecordEntry={chunk:{...chunk},authority:{...authority,scope:{...authority.scope},auth:{...authority.auth}},identity:identity(authority),
      abort:new AbortController(),leases:new Map(),files:new Map(),anticipationFiles:new Map(),work:null!,readers:0,
      changes:new Set(),done:false};
    this.records.set(chunk.id,row);
    // Producer promotion is ordered; no two callers may race its source cursor.
    row.work=this.previous.then(()=>this.download(row)).then(()=>{row.done=true;this.notify(row);},error=>{
      row.failure={error};this.notify(row);throw error;
    });
    this.previous=row.work;
    void row.work.catch(()=>undefined);
    return row;
  }
  private notify(row:RecordEntry){for(const changed of [...row.changes])changed();}
  private async waitChanged(row:RecordEntry,signal:AbortSignal){
    this.check(row);if(signal.aborted)throw Error('Muxed delivery cancelled.');
    await new Promise<void>(resolve=>{
      const changed=()=>{clearTimeout(timer);row.changes.delete(changed);row.abort.signal.removeEventListener('abort',changed);
        signal.removeEventListener('abort',changed);resolve();};
      // Ownership can change independently of publication. Bound that check
      // with the existing polling interval while new files/error wake at once.
      const timer=setTimeout(changed,40);row.changes.add(changed);
      row.abort.signal.addEventListener('abort',changed,{once:true});signal.addEventListener('abort',changed,{once:true});
      if(row.abort.signal.aborted||signal.aborted)changed();
    });
    this.check(row);if(signal.aborted)throw Error('Muxed delivery cancelled.');
  }
  private async wait(row:RecordEntry) {
    this.check(row);
    await new Promise<void>(resolve=>{
      const done=()=>{clearTimeout(timer);row.abort.signal.removeEventListener('abort',done);resolve();};
      const timer=setTimeout(done,40);row.abort.signal.addEventListener('abort',done,{once:true});
    });
    this.check(row);
  }
  private reportRange(row:RecordEntry,file:MuxedTrialFile,
    metadata:{encodeMs?:unknown;sourceReadyAfterClaimMs?:unknown;publishedAfterClaimMs?:unknown},retainMs:number){
    if(!this.deps.onRangeRetained)return;
    // The existing parser still validates producer timings. Missing values are
    // explicit, not zero. encodeMs is producer work, not pure encoding time;
    // retainMs bounds this local store acquisition, not pure network transfer.
    try{void Promise.resolve(this.deps.onRangeRetained({sequence_index:row.chunk.sequence_index!,range_index:file.index,
      start_frame:file.startFrame,frame_count:file.frameCount,producer_work_ms:duration(metadata.encodeMs),
      source_ready_ms:duration(metadata.sourceReadyAfterClaimMs),published_ms:duration(metadata.publishedAfterClaimMs),
      retain_ms:duration(retainMs)})).catch(()=>undefined);}catch{}
  }
  private async reserve(row:RecordEntry,bytes:number):Promise<()=>void>{
    const maxFiles=Math.min(64,this.deps.limits?.maxFiles??64);
    const maxBytes=Math.min(128*1024*1024,this.deps.limits?.maxBytes??128*1024*1024);
    if(bytes>maxBytes)throw Error('Muxed range exceeds byte cap.');
    const previous=this.reservationTail;let next!:()=>void;
    this.reservationTail=new Promise<void>(resolve=>{next=resolve;});
    await previous;
    try{
    while(true){
      this.check(row);
      if(this.reservedFiles<maxFiles&&this.reservedBytes+bytes<=maxBytes){
        this.reservedFiles++;this.reservedBytes+=bytes;
        let released=false;
        return ()=>{if(!released){released=true;this.reservedFiles--;this.reservedBytes-=bytes;}};
      }
      await this.wait(row);
    }
    }finally{next();}
  }
  private async retainIndependent(row:RecordEntry,segment:{index:number;uri?:string;bytes?:number},mediaId:string){
    const unreserve=await this.reserve(row,segment.bytes!);
    let retryDeadline=Date.now()+90000;
    let lease:BufferedMediaLease;
    let cleanupFailed=false;
    try{
      const {BufferedMediaCapacityError,BufferedMediaCleanupError}=await import('../relay/bufferedMedia');
      while(true){
        this.check(row);
        try{lease=await this.retain(row,{id:`muxed-${mediaId}-${segment.index}`,
          path:segment.uri!,bytes:segment.bytes!,contentType:'video/mp4'});break;}
        catch(error){
          // This typed store receipt distinguishes failed internal pin cleanup
          // from a clean abort or transfer rejection. No release handle was
          // returned, so retain its reservation and fail closed on retirement.
          if(error instanceof BufferedMediaCleanupError){cleanupFailed=true;throw error;}
          this.check(row);
          const capacity=error instanceof BufferedMediaCapacityError;
          if(!capacity&&!this.deps.retryable?.(error))throw error;
          if(!capacity&&Date.now()>retryDeadline)throw Error('Muxed source preparation timed out.');
          const waitStarted=Date.now();
          await this.wait(row);
          if(capacity)retryDeadline+=Date.now()-waitStarted;
        }
      }
    }catch(error){
      if(cleanupFailed)row.unconfirmed??={error};else unreserve();
      throw error;
    }
    let releaseTask:Promise<void>|undefined;
    const retained={uri:lease.uri,bytes:lease.bytes,release:()=>releaseTask??=(async()=>{await lease.release();unreserve();})()};
    // Include completed later files in retirement even before they can join
    // the contiguous prefix. Failed releases keep their reservations pinned.
    row.leases.set(segment.index,retained);
    this.check(row);
    if(!this.deps.store.owns(row.authority.scope,lease.uri))throw Error('Muxed file authority ended.');
    if(lease.bytes!==segment.bytes)throw Error('Muxed retained descriptor changed.');
    return retained;
  }
  private async download(row:RecordEntry) {
    let cursor=0,deadline=Date.now()+90000;
    const audio={id:row.chunk.id,phone_request_id:row.chunk.phone_request_id!,url_path:row.chunk.url_path};
    let method:'GET'|'POST'='POST';
    let readyWait=false,mediaId:string|undefined;
    while(true) {
      this.check(row);if(Date.now()>deadline)throw Error('Muxed source preparation timed out.');
      let raw:any;
      try{raw=await this.diagnostics.request(method==='POST'?(readyWait?'wait_ready':'prepare'):'status',
        diagnosticLink=>this.deps.request(method,method==='POST'?PREFIX+(readyWait?'wait-ready':'prepare'):PREFIX+'status/'+this.deps.trialId,
        method==='POST'?{trialId:this.deps.trialId,audio,...(readyWait?{mediaId}:{}),currentIndex:cursor,diagnosticLink}:undefined,row.abort.signal,diagnosticLink),
        {segment_id:String(row.chunk.sequence_index),chunk_id:String(cursor)});}
      catch(error){
        this.check(row);
        // Retry only a typed current transport/capacity interruption. Keep the
        // exact method, media identity and missing-head cursor; no downgrade
        // to an older status-polling protocol on timeout or endpoint errors.
        if(!this.deps.retryable?.(error))throw error;
        await this.wait(row);continue;
      }
      this.check(row);
      const status=parseLiveStatus(raw,this.deps.trialId,audio);
      mediaId=status.mediaId;readyWait=false;
      if(raw.muxedAudio!==true||!Number.isSafeInteger(raw.muxedSamples)||raw.muxedSamples<1||raw.muxedSamples>1441999
        ||Math.abs(raw.muxedSamples-status.frameCount*2000)>=2000||status.state==='unavailable')throw Error('Invalid muxed source.');
      const source=JSON.stringify([status.mediaId,status.frameCount,raw.muxedSamples,status.durationSeconds]);
      if(row.source&&row.source!==source)throw Error('Muxed source changed.');
      row.source=source;
      if(status.sourceState!=='matched'){method='GET';await this.wait(row);continue;}
      const anticipation=raw.anticipation===undefined?undefined:parseAnticipationStatus(raw.anticipation,true);
      const waiting=anticipation?{planId:anticipation.planId,mediaId:anticipation.mediaId,avatarId:anticipation.avatarId,
        sourceFrameCount:anticipation.sourceFrameCount,sourceIndices:[...anticipation.sourceIndices],
        speechEntryFrame:anticipation.speechEntryFrame,exitAfterFrame:anticipation.exitAfterFrame,repeat:anticipation.repeat}:undefined;
      if(row.waiting&&row.waiting!==JSON.stringify(waiting))throw Error('Muxed desktop waiting plan changed.');
      if(waiting&&this.deps.onWaitingPlan&&row.chunk.sequence_index===0&&!row.waiting){
        this.diagnostics.decision('phone.delivery.waiting','state','available_or_active',anticipation?.state??null);
        this.diagnostics.decision('phone.delivery.waiting','repeat',true,waiting.repeat);
        if(!anticipation||!['available','active'].includes(anticipation.state)||!waiting.repeat)
          throw Error('Muxed desktop waiting plan unavailable.');
        row.waiting=JSON.stringify(waiting);
        await this.diagnostics.operation('phone.delivery.waiting_callback',
          ()=>this.deps.onWaitingPlan!(row.chunk,waiting,row.abort.signal),{segment_id:String(row.chunk.sequence_index)});this.check(row);
      }
      // Matching the authenticated WAV precedes publication of the final
      // desktop frame plan. Keep idle playing; never invent a speech mapping.
      if(raw.sourceTimeline===undefined){
        if(row.timeline)throw Error('Muxed frame timeline changed.');
        method=this.readyWaitEnabled?'POST':'GET';readyWait=this.readyWaitEnabled;await this.wait(row);continue;
      }
      const timeline=parseSourceTimeline(raw.sourceTimeline);
      if(timeline.sourceFps!==24||timeline.sourceIndices.length!==status.frameCount)throw Error('Invalid muxed frame timeline.');
      const mapping=JSON.stringify(timeline);
      if(row.timeline&&row.timeline!==mapping)throw Error('Muxed frame timeline changed.');
      row.timeline=mapping;
      if(status.idleChunkReturn&&status.loopFadeMs!==undefined){
        if(anticipation&&(anticipation.sourceFrameCount!==timeline.sourceFrameCount
          ||anticipation.avatarId!==status.idleChunkReturn.avatarId||anticipation.speechEntryFrame!==timeline.sourceIndices[0]))
          throw Error('Muxed desktop entry plan changed.');
        const plan=JSON.stringify({mediaId:status.mediaId,timeline,idleReturn:status.idleChunkReturn,loopFadeMs:status.loopFadeMs,
          ...(anticipation?{anticipation:{planId:anticipation.planId,mediaId:anticipation.mediaId,avatarId:anticipation.avatarId,
            sourceFrameCount:anticipation.sourceFrameCount,sourceIndices:anticipation.sourceIndices,
            speechEntryFrame:anticipation.speechEntryFrame,exitAfterFrame:anticipation.exitAfterFrame,repeat:anticipation.repeat}}:{})});
        if(row.plan&&row.plan!==plan)throw Error('Muxed desktop return plan changed.');row.plan=plan;
        row.totals??={frameCount:status.frameCount,samples:raw.muxedSamples,rangeCount:status.segments.length};
        if(anticipation&&!this.deps.onWaitingPlan&&row.anticipationFiles.size===0){
          // The producer reserves its opening speech window while the exact
          // desktop plan is retained. Advancing speech first retires this lane.
          await this.downloadAnticipation(row,anticipation,status.mediaId,audio);
          method='POST';continue;
        }
      }else if(row.plan)throw Error('Muxed desktop return plan disappeared.');
      for(const [index,file] of row.files) {
        const metadata=raw.segments[index];
        if(['sampleRate','validSamples','delaySamples','paddingSamples','rawSamples'].some(key=>metadata[key]!==file[key as keyof MuxedTrialFile])
          ||(metadata.state==='ready'&&metadata.bytes!==file.bytes))throw Error('Muxed retained descriptor changed.');
      }
      let progress=false,interrupted=false;
      if(this.deps.independent){
        // Only the current source's contiguous ready window is admitted. The
        // store owns its existing two bulk slots; later completions stay pinned
        // but cannot advance publication or become consumer-visible first.
        const batch=status.segments.slice(cursor,cursor+2).filter((segment,offset,window)=>
          segment.state==='ready'&&window.slice(0,offset).every(prior=>prior.state==='ready'));
        for(const segment of batch){
          const metadata=raw.segments[segment.index];
          const samples=segment.index===status.segments.length-1?raw.muxedSamples-segment.startFrame*2000:24000;
          this.validateSamples(metadata,samples);
        }
        const tasks:Promise<{lease:BufferedMediaLease;retainMs:number}|{error:unknown}>[]=batch.map(segment=>{
          const started=Date.now();
          return this.retainIndependent(row,segment,status.mediaId).then(lease=>({lease,retainMs:Date.now()-started}),
            error=>({error}));
        });
        try{
          for(let index=0;index<tasks.length;index++){
            const result=await tasks[index]!;if('error' in result)throw result.error;
            this.check(row);
            const segment=batch[index]!,metadata=raw.segments[segment.index];
            const samples=segment.index===status.segments.length-1?raw.muxedSamples-segment.startFrame*2000:24000;
            const file:MuxedTrialFile={uri:result.lease.uri,bytes:result.lease.bytes,index:segment.index,
              startFrame:segment.startFrame,frameCount:segment.frameCount,validSamples:samples,delaySamples:metadata.delaySamples,
              paddingSamples:metadata.paddingSamples,rawSamples:metadata.rawSamples,sampleRate:48000,fps:24};
            row.files.set(segment.index,file);this.notify(row);this.reportRange(row,file,metadata,result.retainMs);progress=true;
          }
        }catch(error){row.failure={error};this.notify(row);row.abort.abort();await Promise.all(tasks);throw error;}
        // Capacity/reconnect time belongs to retention, not producer failure.
        if(batch.length)deadline=Date.now()+90000;
      }else{
      for(const segment of status.segments) {
        if(segment.state!=='ready'||row.files.has(segment.index))continue;
        if(segment.index!==row.files.size)throw Error('Missing or reordered muxed range.');
        const metadata=raw.segments[segment.index];
        const samples=segment.index===status.segments.length-1?raw.muxedSamples-segment.startFrame*2000:24000;
        if(metadata.sampleRate!==48000||metadata.validSamples!==samples
          ||!Number.isSafeInteger(metadata.delaySamples)||metadata.delaySamples<0||metadata.delaySamples>2048
          ||!Number.isSafeInteger(metadata.paddingSamples)||metadata.paddingSamples<0||metadata.paddingSamples>1023
          ||!Number.isSafeInteger(metadata.rawSamples)||metadata.rawSamples%1024!==0||metadata.rawSamples>28672
          ||metadata.rawSamples-metadata.delaySamples-metadata.paddingSamples!==samples)
          throw Error('Invalid muxed sample range.');
        let lease:BufferedMediaLease;
        const retainStarted=this.deps.onRangeRetained?Date.now():0;
        try{lease=await this.retain(row,{id:`muxed-${status.mediaId}-${segment.index}`,
          path:segment.uri!,bytes:segment.bytes!,contentType:'video/mp4'});}
        catch(error){this.check(row);if(!this.deps.retryable?.(error))throw error;interrupted=true;break;}
        const retainMs=this.deps.onRangeRetained?Date.now()-retainStarted:0;
        try {this.check(row);if(!this.deps.store.owns(row.authority.scope,lease.uri))throw Error('Muxed file authority ended.');}
        catch(error){await lease.release();throw error;}
        row.leases.set(segment.index,lease);
        row.files.set(segment.index,{uri:lease.uri,bytes:lease.bytes,index:segment.index,startFrame:segment.startFrame,
          frameCount:segment.frameCount,validSamples:samples,delaySamples:metadata.delaySamples,
          paddingSamples:metadata.paddingSamples,rawSamples:metadata.rawSamples,sampleRate:48000,fps:24});
        if(Array.from(row.leases.values()).reduce((n,file)=>n+file.bytes,0)>128*1024*1024)
          throw Error('Muxed retained source exceeds byte cap.');
        this.notify(row);
        this.reportRange(row,row.files.get(segment.index)!,metadata,retainMs);
        progress=true;
      }
      }
      cursor=row.files.size;
      if(cursor===status.segments.length){
        if(!this.deps.independent||(row.plan&&row.totals))return;
        // The host accepts only actual range indices. Once all files are
        // retained, await the immutable return plan through ordinary status.
        if(progress)deadline=Date.now()+90000;
        method='GET';readyWait=false;await this.wait(row);continue;
      }
      if(interrupted){method='POST';if(progress)deadline=Date.now()+90000;await this.wait(row);continue;}
      if(status.segments[cursor]?.state==='unavailable')throw Error('Undelivered muxed range retired.');
      if(progress){deadline=Date.now()+90000;method='POST';}
      else {method=this.readyWaitEnabled?'POST':'GET';readyWait=this.readyWaitEnabled;await this.wait(row);}
    }
  }
  private retain(row:RecordEntry,descriptor:BufferedMediaDescriptor):Promise<BufferedMediaLease>{
    return this.diagnostics.request('download',diagnosticLink=>this.deps.store.acquire(
      row.authority.scope,{...descriptor,diagnosticLink},row.abort.signal));
  }
  private validateSamples(metadata:any,samples:number){
    if(metadata.sampleRate!==48000||metadata.validSamples!==samples
      ||!Number.isSafeInteger(metadata.delaySamples)||metadata.delaySamples<0||metadata.delaySamples>2048
      ||!Number.isSafeInteger(metadata.paddingSamples)||metadata.paddingSamples<0||metadata.paddingSamples>1023
      ||!Number.isSafeInteger(metadata.rawSamples)||metadata.rawSamples%1024!==0||metadata.rawSamples>28672
      ||metadata.rawSamples-metadata.delaySamples-metadata.paddingSamples!==samples)throw Error('Invalid muxed sample range.');
  }
  private async downloadAnticipation(row:RecordEntry,opening:ReturnType<typeof parseAnticipationStatus>,mediaId:string,
    audio:{id:string;phone_request_id:string;url_path:string}):Promise<void>{
    if(opening.state!=='available'||row.chunk.sequence_index!==0||opening.sourceIndices.length>648)
      throw Error('Muxed desktop anticipation unavailable.');
    const identity=(plan:typeof opening)=>JSON.stringify([plan.planId,plan.mediaId,plan.avatarId,plan.sourceFrameCount,
      plan.sourceIndices,plan.speechEntryFrame,plan.exitAfterFrame,plan.repeat]);
    const expected=identity(opening);let cursor=0,method:'GET'|'POST'='POST',deadline=Date.now()+90000;
    while(cursor<opening.segments.length){
      this.check(row);if(Date.now()>deadline)throw Error('Muxed anticipation transfer stalled.');
      let raw:any;
      try{raw=method==='GET'
        ?await this.diagnostics.request('status',link=>this.deps.request('GET',`${PREFIX}status/${this.deps.trialId}`,undefined,row.abort.signal,link))
        :await this.deps.request('POST',`${PREFIX}anticipation-cursor`,{trialId:this.deps.trialId,audio,mediaId,cursor},row.abort.signal);}
      catch(error){this.check(row);if(!this.deps.retryable?.(error))throw error;await this.wait(row);continue;}
      this.check(row);parseLiveStatus(raw,this.deps.trialId,audio);
      const plan=parseAnticipationStatus(raw.anticipation,true);
      if(raw.muxedAudio!==true||raw.mediaId!==mediaId||identity(plan)!==expected||plan.state!=='active'||plan.cursor!==cursor)
        throw Error('Muxed anticipation source changed.');
      const segment=plan.segments[cursor];
      if(!segment)throw Error('Muxed anticipation range missing.');
      if(segment.state!=='ready'){method='GET';await this.wait(row);continue;}
      let lease:BufferedMediaLease;
      try{lease=await this.retain(row,{id:`muxed-anticipation-${plan.mediaId}-${cursor}`,
        path:segment.uri!,bytes:segment.bytes!,contentType:'video/mp4'});}
      catch(error){this.check(row);if(!this.deps.retryable?.(error))throw error;await this.wait(row);continue;}
      try{this.check(row);if(!this.deps.store.owns(row.authority.scope,lease.uri))throw Error('Muxed anticipation authority ended.');}
      catch(error){await lease.release();throw error;}
      row.leases.set(-cursor-1,lease);
      row.anticipationFiles.set(cursor,{uri:lease.uri,bytes:lease.bytes,index:cursor,startFrame:segment.startFrame,
        frameCount:segment.frameCount,sampleRate:48000,fps:24,validSamples:segment.validSamples!,
        delaySamples:segment.delaySamples!,paddingSamples:segment.paddingSamples!,rawSamples:segment.rawSamples!});
      if(Array.from(row.leases.values()).reduce((n,file)=>n+file.bytes,0)>128*1024*1024)
        throw Error('Muxed retained source exceeds byte cap.');
      cursor++;method='POST';deadline=Date.now()+90000;
    }
    const ended:any=await this.deps.request('POST',`${PREFIX}anticipation-cursor`,
      {trialId:this.deps.trialId,audio,mediaId,cursor:null},row.abort.signal);
    this.check(row);parseLiveStatus(ended,this.deps.trialId,audio);
    const final=parseAnticipationStatus(ended.anticipation,true);
    if(ended.muxedAudio!==true||ended.mediaId!==mediaId||identity(final)!==expected||final.state!=='ended')
      throw Error('Muxed anticipation retirement changed.');
  }
  private async acquireRetained(chunk:AudioChunk,signal:AbortSignal,minRanges?:number):Promise<BufferedMediaLease>{
    if(signal.aborted)throw Error('Muxed delivery cancelled.');
    const row=this.record(chunk);row.readers++;
    let released=false;
    const release=async()=>{
      if(released)return;released=true;row.readers--;
      if(!row.readers)await this.retire(row);
    };
    const abort=()=>{if(!this.deps.independent)row.abort.abort();};signal.addEventListener('abort',abort,{once:true});
    try {
      if(minRanges===undefined){
        if(this.deps.independent)await this.waitComplete(chunk,signal);else await row.work;
      }
      else while(!row.plan||!row.totals||row.files.size<Math.min(minRanges,row.totals.rangeCount)){
        this.check(row);if(row.done)throw Error('Muxed desktop continuation unavailable.');await this.waitChanged(row,signal);
      }
      this.check(row);if(signal.aborted)throw Error('Muxed delivery cancelled.');
      const first=row.files.get(0)!;
      return {uri:first.uri,bytes:Array.from(row.files.values()).reduce((n,file)=>n+file.bytes,0),release};
    }catch(error){await release();throw error;}
    finally {signal.removeEventListener('abort',abort);}
  }
  acquire=async(chunk:AudioChunk,signal:AbortSignal):Promise<BufferedMediaLease>=>this.acquireRetained(chunk,signal);
  async waitComplete(chunk:AudioChunk,signal:AbortSignal):Promise<void>{
    const row=this.records.get(chunk.id);if(!row)throw Error('Muxed source unavailable.');
    while(!row.done){
      this.check(row);if(signal.aborted)throw Error('Muxed delivery cancelled.');await this.waitChanged(row,signal);
    }
    this.check(row);if(signal.aborted)throw Error('Muxed delivery cancelled.');
  }
  acquireProgressive=async(chunk:AudioChunk,signal:AbortSignal,minRanges=2):Promise<BufferedMediaLease>=>{
    if(!Number.isSafeInteger(minRanges)||minRanges<1)throw Error('Invalid muxed startup range count.');
    return this.acquireRetained(chunk,signal,minRanges);
  };
  sourceTotals(chunk:AudioChunk):MuxedSourceTotals{
    const row=this.records.get(chunk.id);if(!row)throw Error('Muxed source unavailable.');this.check(row);
    if(!row.plan||!row.totals)throw Error('Muxed desktop continuation unavailable.');
    return {...row.totals};
  }
  async waitForFiles(chunk:AudioChunk,first:number,signal:AbortSignal):Promise<MuxedTrialFile[]>{
    if(!Number.isSafeInteger(first)||first<0||first>60)throw Error('Invalid muxed range cursor.');
    const row=this.records.get(chunk.id);if(!row)throw Error('Muxed source unavailable.');
    while(true){
      this.check(row);if(signal.aborted)throw Error('Muxed delivery cancelled.');
      if(row.plan&&row.totals){
        if(first>row.totals.rangeCount)throw Error('Invalid muxed range cursor.');
        const files=this.files(chunk).filter(file=>file.index>=first);
        if(files.length)return files;
        if(row.done)return [];
      }else if(row.done)throw Error('Muxed desktop continuation unavailable.');
      await this.waitChanged(row,signal);
    }
  }
  owns(chunk:AudioChunk,uri:string):boolean {
    const row=this.records.get(chunk.id);if(!row)return false;
    try{this.check(row);}catch{return false;}
    return [...row.files.values(),...row.anticipationFiles.values()].some(file=>file.uri===uri&&this.deps.store.owns(row.authority.scope,uri));
  }
  files(chunk:AudioChunk):MuxedTrialFile[] {
    const row=this.records.get(chunk.id);if(!row)throw Error('Muxed source unavailable.');
    this.check(row);
    if(Array.from(row.files.values()).some(file=>!this.deps.store.owns(row.authority.scope,file.uri)))throw Error('Muxed file authority ended.');
    return Array.from(row.files.values()).map(file=>({...file}));
  }
  prepared(chunk:AudioChunk):MuxedTrialPlan {
    const row=this.records.get(chunk.id);if(!row)throw Error('Muxed source unavailable.');this.check(row);
    if(!row.plan)throw Error('Muxed desktop continuation unavailable.');
    return JSON.parse(row.plan) as MuxedTrialPlan;
  }
  /** Exact authority comes from the retained authenticated record, not a plan
   * or a mutable queue chunk. Missing recovery epoch denotes original epoch0. */
  continuousDescriptor(chunk:AudioChunk,plan:MuxedTrialPlan,ticket:string):ContinuousDescriptor {
    const row=this.records.get(chunk.id);if(!row)throw Error('Muxed source unavailable.');this.check(row);
    if(row.chunk.phone_request_id!==chunk.phone_request_id||row.chunk.sequence_index!==chunk.sequence_index
      ||row.chunk.url_path!==chunk.url_path||row.chunk.playback_recovery_epoch!==chunk.playback_recovery_epoch
      ||row.plan!==JSON.stringify(plan)||row.authority.ticket!==ticket||!row.totals)
      throw Error('Muxed continuous descriptor changed.');
    const recoveryEpoch=row.chunk.playback_recovery_epoch??0,connectionEpoch=row.authority.auth.connection_epoch;
    if(!Number.isSafeInteger(recoveryEpoch)||recoveryEpoch<0||!connectionEpoch)
      throw Error('Invalid muxed continuous authority.');
    const timeline=plan.timeline,quality=plan.idleReturn.videoQuality;
    return Object.freeze({ticket:row.authority.ticket,owner:row.authority.scope.owner,connectionEpoch,recoveryEpoch,
      replyId:row.authority.scope.replyId,chunkId:row.chunk.id,sequenceIndex:row.chunk.sequence_index!,
      expiresAtMs:row.authority.scope.expiresAt,mediaId:plan.mediaId,
      plan:Object.freeze({frames:row.totals.frameCount,samples:row.totals.samples}),motionId:timeline.motionId,
      sourceFrameCount:timeline.sourceFrameCount,avatarId:plan.idleReturn.avatarId,
      quality:Object.freeze({kbps:quality.video_kbps,width:quality.video_width,fps:quality.video_fps}),
      firstSourceFrame:timeline.sourceIndices[0]!,lastSourceFrame:timeline.sourceIndices.at(-1)!,
      idleReturnEntry:plan.idleReturn.startFrame,unsupportedAnticipation:Boolean(plan.anticipation)});
  }
  anticipationFiles(chunk:AudioChunk):MuxedTrialFile[]{
    const row=this.records.get(chunk.id);if(!row)throw Error('Muxed source unavailable.');this.check(row);
    if(Array.from(row.anticipationFiles.values()).some(file=>!this.deps.store.owns(row.authority.scope,file.uri)))
      throw Error('Muxed anticipation authority ended.');
    return Array.from(row.anticipationFiles.values()).map(file=>({...file}));
  }
  bindNative(chunk:AudioChunk,detach:()=>Promise<void>):()=>Promise<void> {
    const row=this.records.get(chunk.id);if(!row)throw Error('Muxed source unavailable.');
    this.check(row);if(row.native)throw Error('Muxed native reader already bound.');
    row.native=detach;
    return ()=>this.detach(row);
  }
  private detach(row:RecordEntry):Promise<void> {
    if(!row.detaching)row.detaching=row.native?row.native():Promise.resolve();
    return row.detaching;
  }
  private retire(row:RecordEntry):Promise<void> {
    if(row.releasing)return row.releasing;
    row.abort.abort();
    row.releasing=(async()=>{
      await row.work.catch(()=>undefined);
      await this.detach(row); // A failed detach keeps files pinned; no unsafe unlink.
      await Promise.all(Array.from(row.leases.values(),lease=>lease.release()));
      if(row.unconfirmed)throw row.unconfirmed.error;
      row.leases.clear();row.files.clear();row.anticipationFiles.clear();
      if(this.records.get(row.chunk.id)===row)this.records.delete(row.chunk.id);
    })();
    return row.releasing;
  }
  quiesce():Promise<void> {
    if(this.quiescing)return this.quiescing;
    // Stop admission and join transfers without releasing files. Shutdown
    // must do this even if native retirement failed and its reader stays pinned.
    this.closed=true;
    const rows=[...this.records.values()];
    for(const row of rows)row.abort.abort();
    this.quiescing=Promise.allSettled(rows.map(row=>row.work)).then(()=>undefined);
    return this.quiescing;
  }
  close():Promise<void> {
    if(this.closing)return this.closing;
    this.closed=true;
    for(const row of this.records.values())row.abort.abort();
    this.closing=Promise.all(Array.from(this.records.values(),row=>this.retire(row))).then(()=>undefined);
    return this.closing;
  }
}
