import type {AudioPlayer} from 'expo-audio';
import type {AudioChunk} from '../api/types';
import type {MuxedTrialDelivery,MuxedTrialPlan,MuxedTrialFile} from './muxedTrialDelivery';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import {PlanTransactionTrace} from '../diagnostics/planTransaction';
import {parseRunHandle,parseSourceGrant,parseTail,parseAppendResult,parseJournalBatch,parseSnapshot,parseVisualEpoch,sameVisual,sameSource,sameRun,sameTailSource} from './muxedContinuousProtocol';
import type {RunHandle,SourceGrant,TailCursor,PhysicalTail,VisualEpoch,ReturnDescriptor,RunSnapshot,ContinuousMetadata,ContinuousBufferedAudio} from './muxedContinuousProtocol';

type Native=AudioPlayer&Record<string,(request:unknown)=>Promise<unknown>>;
type Delivery=Pick<MuxedTrialDelivery,'files'|'owns'|'bindNative'|'continuousDescriptor'>;
type Progressive=Pick<MuxedTrialDelivery,'sourceTotals'|'waitForFiles'>;
type Entry={chunk:AudioChunk;grant?:SourceGrant;stage?:string;first:number;abort:AbortController;
  pump?:Promise<void>;retiring?:Promise<void>;closed?:boolean;detach:()=>Promise<void>};
type VisualEntry={descriptor:ReturnDescriptor;identity:string;parent:SourceGrant;epoch?:VisualEpoch;
  first:number;releasedThrough:number;signal:AbortSignal;owns:()=>boolean;
  stage?:string;stageTail?:PhysicalTail;stageFiles?:string};
const methods=['ncOpenContinuousMuxed','ncStageContinuousMuxed','ncAppendContinuousMuxed','ncReadContinuousMuxed',
  'ncAcknowledgeContinuousMuxed','ncSealContinuousMuxed','ncRetireContinuousMuxedSource',
  'ncRetireContinuousMuxedRun','ncInvalidateContinuousMuxed','ncDropContinuousMuxedStage'];
function result(value:unknown):Record<string,unknown>{
  if(!value||typeof value!=='object'||(value as {version?:unknown}).version!==2)
    throw Error('Invalid continuous native response.');
  return value as Record<string,unknown>;
}
const wait=()=>new Promise<void>(resolve=>setTimeout(resolve,25));
function sourceIdentity(chunk:AudioChunk):string {
  // Async waveform enrichment does not change the retained playback source.
  return JSON.stringify({...chunk,spectrum_status:undefined,spectrum_version:undefined,spectrum_url_path:undefined});
}
type PumpPhase='source_totals'|'wait_files'|'file_authority'|'stage'|'journal_read'|'append'|'append_result'|'source_identity';
const nativePumpFailureMessages=new Map([
  ['Invalid continuous request object','native_request_object'],['Invalid continuous request fields','native_request_fields'],
  ['Invalid continuous integer','native_continuous_integer'],['Invalid continuous file batch','native_file_batch'],
  ['Invalid muxed integer','native_muxed_integer'],['Invalid muxed URI','native_muxed_uri'],
  ['Failed requirement.','native_requirement'],['Check failed.','native_check'],
  ['Unknown continuous run','native_run_unknown'],['Unknown continuous source','native_source_unknown'],
  ['Unknown continuous stage','native_stage_unknown'],['Continuous output owner ended','native_owner_ended'],
  ['Continuous staging rejected','native_staging_rejected'],['Continuous stage ownership unconfirmed','native_stage_ownership'],
  ['Continuous successor rejected','native_successor_rejected'],['Continuous source ownership unconfirmed','native_source_ownership'],
  ['Continuous append unconfirmed','native_append_unconfirmed'],['Invalid continuous journal cursor','native_journal_cursor'],
]);
const pumpFailureMessages=new Map([...nativePumpFailureMessages,
  ['Muxed source unavailable.','source_unavailable'],['Muxed desktop continuation unavailable.','source_continuation_unavailable'],
  ['Muxed reply authority ended.','reply_authority_ended'],['Muxed delivery cancelled.','delivery_cancelled'],
  ['Muxed file authority ended.','file_authority_ended'],['Invalid muxed range cursor.','invalid_range_cursor'],
  ['Muxed source changed.','source_changed'],['Invalid muxed source.','invalid_source'],
  ['Invalid muxed sample range.','invalid_sample_range'],['Muxed retained descriptor changed.','retained_descriptor_changed'],
  ['Missing or reordered muxed range.','range_reordered'],['Undelivered muxed range retired.','range_retired'],
  ['Muxed source preparation timed out.','source_preparation_timeout'],['Muxed range exceeds byte cap.','range_byte_cap'],
  ['Muxed retained source exceeds byte cap.','source_byte_cap'],['Muxed frame timeline changed.','frame_timeline_changed'],
  ['Invalid muxed frame timeline.','invalid_frame_timeline'],['Muxed desktop entry plan changed.','desktop_entry_changed'],
  ['Muxed desktop return plan changed.','desktop_return_changed'],['Muxed desktop return plan disappeared.','desktop_return_missing'],
  ['Invalid continuous native response.','invalid_native_response'],['Invalid continuous native stage.','invalid_native_stage'],
  ['Continuous muxed pump source changed.','pump_source_changed'],
]);
function pumpFailureCategory(error:unknown):string {
  try {
    // Do not coerce arbitrary objects or invoke message/stack accessors.
    if(!(error instanceof Error))return 'other';
    const message=Object.getOwnPropertyDescriptor(error,'message')?.value;
    if(typeof message!=='string'||message.length>512)return 'other';
    const exact=pumpFailureMessages.get(message);if(exact)return exact;
    // Expo's current AudioPlayer wrapper preserves the exact static native cause.
    // Require the entire known shape; appended content is never a known cause.
    const wrapped=/^Call to function 'AudioPlayer\.nc(?:Stage|Read|Append)ContinuousMuxed' has been rejected\.\r?\n→ Caused by: java\.lang\.(?:IllegalArgumentException|IllegalStateException): ([^\r\n]+)$/.exec(message);
    return wrapped?nativePumpFailureMessages.get(wrapped[1]!)??'other':'other';
  } catch {return 'other';}
}
function pumpNumber(value:unknown,max:number):number {
  return typeof value==='number'&&Number.isSafeInteger(value)&&value>=0&&value<=max?value:-1;
}
function recordPumpFailure(error:unknown,details:{phase:PumpPhase;sequence_index:unknown;firstRange:number;batchCount:number;
  nextRange?:number;appendRevision?:number;acknowledgedCursor:number}):void {
  try {void Promise.resolve(recordPhoneDebug('error','continuous_pump_failure',{
    phase:details.phase,category:pumpFailureCategory(error),sequence_index:pumpNumber(details.sequence_index,63),
    firstRange:pumpNumber(details.firstRange,60),batchCount:pumpNumber(details.batchCount,6),
    ...(details.nextRange===undefined?{}:{nextRange:pumpNumber(details.nextRange,60)}),
    ...(details.appendRevision===undefined?{}:{appendRevision:pumpNumber(details.appendRevision,Number.MAX_SAFE_INTEGER)}),
    acknowledgedCursor:pumpNumber(details.acknowledgedCursor,256),
  })).catch(()=>undefined);}catch { /* Observation cannot delay fencing or replace the original failure. */ }
}

/** Native file/output lifetime is separate from the shared registered player.
 * No method in this owner plays, rebinds, or pauses a speech boundary. */
export class MuxedContinuousSession {
  private diagnostics?:PlanTransactionTrace;
  private player?:Native;
  private run?:RunHandle;
  private entries=new Map<string,Entry>();
  private operations=new Set<Promise<unknown>>();
  private serial:Promise<unknown>=Promise.resolve();
  private journalSerial:Promise<unknown>=Promise.resolve();
  private stopped=false;
  private failure?:unknown;
  private invalidating?:Promise<void>;
  private retiring?:Promise<void>;
  private retired=false;
  private acknowledged=0;
  private visual?:VisualEntry;
  private observed?:RunSnapshot;
  constructor(private readonly delivery:Delivery,private readonly progressive?:Progressive){}
  private call(name:string,body:Record<string,unknown>):Promise<unknown>{
    if(!this.player)throw Error('Continuous muxed player unavailable.');
    const invoke=(link?:{trace_id:string;operation_id:string;event_id:string|null})=>{
      // Expo's non-null Kotlin map conversion cannot carry a suppressed event as null.
      const diagnosticLink=link?{trace_id:link.trace_id,operation_id:link.operation_id,
        ...(link.event_id!==null?{event_id:link.event_id}:{})}:undefined;
      return this.player![name]!({version:2,...body,...(diagnosticLink?{diagnosticLink}:{})});
    };
    const work=this.diagnostics?this.diagnostics.observeCall('phone.native.'+name,invoke):invoke();this.operations.add(work);
    void work.then(()=>this.operations.delete(work),()=>this.operations.delete(work));return work;
  }
  private mutate<T>(fn:()=>Promise<T>):Promise<T>{
    const work=this.serial.then(fn);this.serial=work.then(()=>undefined,()=>undefined);return work;
  }
  private journal<T>(fn:()=>Promise<T>):Promise<T>{
    const work=this.journalSerial.then(fn);this.journalSerial=work.then(()=>undefined,()=>undefined);return work;
  }
  private check(signal?:AbortSignal){if(this.stopped||signal?.aborted)throw Error('Continuous muxed owner ended.');
    if(this.failure)throw this.failure;}
  private exact(run:RunHandle){if(!this.run||!sameRun(run,this.run))throw Error('Continuous muxed run changed.');}
  private own(chunk:AudioChunk,files:MuxedTrialFile[]){
    if(!files.length||files.some(f=>!this.delivery.owns(chunk,f.uri)))throw Error('Muxed file authority ended.');
  }
  private entry(chunk:AudioChunk):Entry {
    const prior=this.entries.get(chunk.id);if(prior){
      if(sourceIdentity(prior.chunk)!==sourceIdentity(chunk))throw Error('Continuous muxed source changed.');return prior;}
    if(this.entries.size>=64)throw Error('Muxed source capacity reached.');
    const entry:Entry={chunk:{...chunk},first:0,abort:new AbortController(),detach:async()=>{
      if(entry.closed)return;
      if(!entry.grant)throw Error('Continuous muxed source closure unconfirmed.');
      await this.retireSource(entry.grant);
    }};
    entry.detach=this.delivery.bindNative(chunk,entry.detach);this.entries.set(chunk.id,entry);return entry;
  }
  async open(player:AudioPlayer,chunk:AudioChunk,plan:MuxedTrialPlan,ticket:string,signal:AbortSignal,
    onAcknowledged?:()=>Promise<void>){
    if(this.run&&!this.retiring)throw Error('Continuous muxed run already open.');
    await this.retiring;this.run=undefined;this.retiring=undefined;this.invalidating=undefined;this.stopped=false;this.retired=false;
    this.entries=new Map();this.visual=undefined;this.observed=undefined;this.acknowledged=0;this.player=player as Native;
    // The existing native UUID joins callback evidence to these RPCs; never log request bodies or tickets.
    try{const id=player.id;
      this.diagnostics=new PlanTransactionTrace(typeof id==='string'&&/^[a-f0-9-]{36}$/i.test(id)?id:'native-player-id-unavailable');
    }catch{this.diagnostics=undefined;}
    if(methods.some(name=>typeof this.player![name]!=='function'))throw Error('Update NC Remote for continuous muxed queue version2.');
    this.check(signal);const entry=this.entry(chunk),files=this.delivery.files(chunk).slice(0,2);this.own(chunk,files);
    const descriptor=this.delivery.continuousDescriptor(chunk,plan,ticket);
    const raw=result(await this.call('ncOpenContinuousMuxed',{descriptor,files}));
    this.run=parseRunHandle(raw.run);const source=parseSourceGrant(raw.source,this.run),tail=parseTail(raw.tail,this.run);
    if(tail.kind!=='speech'||source.chunkId!==chunk.id||source.sequenceIndex!==chunk.sequence_index||!sameSource(tail.source,source))
      throw Error('Continuous muxed initial grant changed.');
    entry.grant=source;entry.first=files.length;
    await onAcknowledged?.();
    if(signal.aborted){await this.invalidate(this.run,'stop');throw Error('Continuous muxed owner ended.');}
    this.startPump(entry);
    const continuous:ContinuousMetadata={run:this.run,source,tail};
    return {player,continuous,dispose:()=>undefined,detach:async()=>{
      await this.invalidate(continuous.run,'stop');await this.retireRun(continuous.run);
    }};
  }
  async append(tail:TailCursor,chunk:AudioChunk,plan:MuxedTrialPlan,ticket:string,signal:AbortSignal){
    this.exact(tail.source.run);this.check(signal);
    const descriptor=this.delivery.continuousDescriptor(chunk,plan,ticket),entry=this.entry(chunk);
    return this.mutate(async()=>{
      this.check(signal);if(entry.grant)throw Error('Continuous muxed source already admitted.');
      if(!entry.stage){const files=this.delivery.files(chunk).slice(0,2);this.own(chunk,files);
        const stage=result(await this.call('ncStageContinuousMuxed',{run:this.run,descriptor,files}));
        if(stage.kind==='blocked'&&stage.reason==='capacity')return {kind:'blocked',reason:'capacity'} as const;
        if(stage.kind!=='staged'||typeof stage.stageId!=='string'||!stage.stageId)throw Error('Invalid continuous native stage.');
        entry.stage=stage.stageId;entry.first=files.length;}
      this.check(signal);
      const appended=parseAppendResult(result(await this.call('ncAppendContinuousMuxed',{stageId:entry.stage,tail})),this.run!);
      if(appended.kind==='admitted'){
        if(appended.source.chunkId!==chunk.id||appended.source.sequenceIndex!==chunk.sequence_index)
          throw Error('Continuous muxed appended grant changed.');
        entry.grant=appended.source;entry.stage=undefined;this.startPump(entry);
      }
      return appended;
    });
  }
  private visualCurrent(entry:VisualEntry){
    this.check(entry.signal);
    if(!entry.owns()||entry.descriptor.expiresAtMs<=Date.now())throw Error('Continuous visual scope ended.');
  }
  private ownedVisual(epoch:VisualEpoch):VisualEntry {
    this.exact(epoch.run);const entry=this.visual;
    if(!entry?.epoch||!sameVisual(entry.epoch,epoch))throw Error('Continuous visual epoch changed.');
    return entry;
  }
  /** Position comes only from the existing owned native journal observer.
   * The copied sink watermark is cumulative within this visual epoch. */
  visualPosition(epoch:VisualEpoch):{index:number;seconds:number}|null {
    this.visualCurrent(this.ownedVisual(epoch));
    const snapshot=this.observed,clock=snapshot?.clock;
    if(!snapshot||snapshot.state!=='open'&&snapshot.state!=='sealed'||clock?.kind!=='visual')return null;
    if(!sameVisual(clock.source,epoch)||snapshot.tail.kind!=='visual'||!sameVisual(snapshot.tail.source,epoch))
      throw Error('Continuous visual clock changed.');
    // Native may already have committed a refill whose JS ACK is still pending.
    // Use its copied installed tail, not the earlier local append cursor.
    const count=snapshot.tail.nextRange;
    if(clock.seconds>count*0.5)throw Error('Continuous visual clock range changed.');
    const index=Math.min(count-1,Math.floor(clock.seconds*2));
    return {index,seconds:clock.seconds-index*0.5};
  }
  private async readBatch(run:RunHandle,afterCursor:number){
    const batch=parseJournalBatch(await this.call('ncReadContinuousMuxed',{run,afterCursor}),run,afterCursor);
    this.observed=batch.snapshot;return batch;
  }
  private visualFiles(entry:VisualEntry,files:MuxedTrialFile[],first:number){
    this.visualCurrent(entry);
    if(!files.length||files.length>6||first<0||first+files.length>10006
      ||files.some((file,index)=>file.index!==first+index))throw Error('Continuous visual range changed.');
  }
  private async dropVisualStage(entry:VisualEntry){
    if(entry.stage &&await this.call('ncDropContinuousMuxedStage',{run:this.run,stageId:entry.stage})!==true)
      throw Error('Continuous visual stage closure unconfirmed.');
    entry.stage=undefined;entry.stageTail=undefined;entry.stageFiles=undefined;
  }
  private async appendVisualBatch(entry:VisualEntry,tail:PhysicalTail,files:MuxedTrialFile[]){
    this.visualFiles(entry,files,entry.first);
    const identity=JSON.stringify(files);
    if(entry.stage &&entry.stageFiles!==identity)throw Error('Continuous visual staged range changed.');
    if(entry.stageTail &&(!sameTailSource(entry.stageTail,tail)||entry.stageTail.nextRange!==tail.nextRange
      ||entry.stageTail.appendRevision!==tail.appendRevision))await this.dropVisualStage(entry);
    if(!entry.stage){
      const raw=result(await this.call(tail.kind==='speech'?'ncStageContinuousMuxedReturn':'ncStageContinuousMuxedVisual',
        tail.kind==='speech'?{tail,descriptor:entry.descriptor,files}:{tail,firstRange:entry.first,files}));
      if(raw.kind==='blocked'&&raw.reason==='capacity')return {kind:'blocked',reason:'capacity'} as const;
      if(raw.kind==='blocked'&&raw.reason==='tail_changed')return {kind:'blocked',reason:'tail_changed'} as const;
      if(raw.kind!=='staged'||typeof raw.stageId!=='string'||!raw.stageId)throw Error('Invalid continuous visual stage.');
      entry.stage=raw.stageId;entry.stageTail=parseTail(tail,this.run!);entry.stageFiles=identity;
    }
    this.visualCurrent(entry);
    const raw=result(await this.call('ncAppendContinuousMuxedReturn',{stageId:entry.stage,tail}));
    if(raw.kind==='blocked'&&raw.reason==='tail_changed'){
      await this.dropVisualStage(entry);return {kind:'blocked',reason:'tail_changed'} as const;
    }
    if(raw.kind!=='admitted')throw Error('Continuous visual append unconfirmed.');
    const visual=parseVisualEpoch(raw.visual,this.run!);
    if(!sameSource(visual.parent,entry.parent)||entry.epoch&&!sameVisual(visual,entry.epoch))
      throw Error('Continuous visual epoch changed.');
    entry.epoch=visual;entry.first+=files.length;entry.stage=undefined;entry.stageTail=undefined;entry.stageFiles=undefined;
    this.visualCurrent(entry);
    return {kind:'admitted',visual} as const;
  }
  async appendFinalReturn(tail:TailCursor,descriptor:ReturnDescriptor,files:MuxedTrialFile[],signal:AbortSignal,owns:()=>boolean){
    this.exact(tail.source.run);this.check(signal);
    return this.mutate(async()=>{
      this.check(signal);
      const parent=this.entries.get(tail.source.chunkId)?.grant;
      if(!parent||!sameSource(parent,tail.source)||descriptor.finalSequenceIndex!==parent.sequenceIndex)
        throw Error('Continuous RETURN parent changed.');
      const identity=JSON.stringify(descriptor);
      let entry=this.visual;
      if(entry &&(entry.identity!==identity||!sameSource(entry.parent,parent)))throw Error('Continuous RETURN descriptor changed.');
      if(!entry){
        if(['ncStageContinuousMuxedReturn','ncStageContinuousMuxedVisual','ncAppendContinuousMuxedReturn','ncPruneContinuousMuxedVisual']
          .some(name=>typeof this.player![name]!=='function'))throw Error('Continuous RETURN native contract unavailable.');
        const copy=Object.freeze({...descriptor,quality:Object.freeze({...descriptor.quality})});
        entry=this.visual={descriptor:copy,identity,parent,first:0,releasedThrough:0,signal,owns};
      }
      this.visualCurrent(entry);if(!owns())throw Error('Continuous visual scope ended.');
      if(entry.epoch)return {kind:'admitted',visual:entry.epoch} as const;
      if(files.length<2)throw Error('Continuous RETURN prefix unavailable.');
      return this.appendVisualBatch(entry,tail,files);
    });
  }
  async appendVisual(epoch:VisualEpoch,files:MuxedTrialFile[],first:number):Promise<boolean>{
    const entry=this.ownedVisual(epoch);
    return this.mutate(async()=>{
      this.visualCurrent(entry);
      if(first!==entry.first)throw Error('Continuous visual range changed.');
      // A queued journal ACK may advance before this action executes.
      const tail=(await this.journal(()=>this.readBatch(epoch.run,this.acknowledged))).snapshot.tail;
      if(tail.kind!=='visual'||!sameVisual(tail.source,epoch)||tail.nextRange!==first)
        throw Error('Continuous visual native tail changed.');
      return (await this.appendVisualBatch(entry,tail,files)).kind==='admitted';
    });
  }
  async pruneVisual(epoch:VisualEpoch,beforeIndex:number):Promise<number|null>{
    const entry=this.ownedVisual(epoch);
    return this.mutate(async()=>{
      this.visualCurrent(entry);
      if(!Number.isSafeInteger(beforeIndex)||beforeIndex<0||beforeIndex>entry.first)
        throw Error('Continuous visual prune range changed.');
      const raw=result(await this.call('ncPruneContinuousMuxedVisual',{visual:epoch,beforeIndex}));
      if(raw.kind==='pending')return null;
      const through=raw.releasedThrough;
      if(raw.kind!=='pruned'||!sameVisual(parseVisualEpoch(raw.visual,this.run!),epoch)
        ||typeof through!=='number'||!Number.isSafeInteger(through)||through<entry.releasedThrough||through>entry.first)
        throw Error('Continuous visual closure unconfirmed.');
      this.visualCurrent(entry);entry.releasedThrough=through;return through;
    });
  }
  private startPump(entry:Entry){
    if(!this.progressive||entry.pump)return;
    let phase:PumpPhase='source_totals',firstRange=entry.first,batchCount=0;
    let nextRange:number|undefined,appendRevision:number|undefined;
    entry.pump=(async()=>{
      const totals=this.progressive!.sourceTotals(entry.chunk);
      while(entry.first<totals.rangeCount){
        phase='wait_files';firstRange=entry.first;batchCount=0;nextRange=appendRevision=undefined;
        this.check(entry.abort.signal);
        const files=(await this.progressive!.waitForFiles(entry.chunk,entry.first,entry.abort.signal)).slice(0,6);
        batchCount=files.length;phase='file_authority';this.own(entry.chunk,files);
        let stage:string|undefined;
        while(true){phase='stage';this.check(entry.abort.signal);
          const admitted=await this.mutate(async()=>{
            this.check(entry.abort.signal);
            if(!stage){const raw=result(await this.call('ncStageContinuousMuxed',{source:entry.grant,firstRange:entry.first,files}));
              if(raw.kind==='blocked'&&raw.reason==='capacity')return false;
              if(raw.kind!=='staged'||typeof raw.stageId!=='string')throw Error('Invalid continuous native stage.');
              stage=entry.stage=raw.stageId;}
            this.check(entry.abort.signal);
            phase='journal_read';nextRange=appendRevision=undefined;
            const snapshot=(await this.journal(()=>this.readBatch(this.run!,this.acknowledged))).snapshot;
            nextRange=snapshot.tail.nextRange;appendRevision=snapshot.tail.appendRevision;
            this.check(entry.abort.signal);
            phase='append';const raw=await this.call('ncAppendContinuousMuxed',{stageId:stage,tail:snapshot.tail});
            phase='append_result';const value=parseAppendResult(result(raw),this.run!);
            if(value.kind==='blocked')return false;
            phase='source_identity';
            if(!sameSource(value.source,entry.grant!))throw Error('Continuous muxed pump source changed.');
            entry.stage=undefined;return true;
          });
          if(admitted){entry.first+=files.length;break;}await wait();
        }
      }
    })().catch(error=>{if(!this.stopped&&!entry.abort.signal.aborted){
      recordPumpFailure(error,{phase,sequence_index:entry.chunk.sequence_index,firstRange,batchCount,
        nextRange,appendRevision,acknowledgedCursor:this.acknowledged});this.failure=error;
      if(this.run)void this.invalidate(this.run,'failure').catch(()=>undefined);throw error;}});
    void entry.pump.catch(()=>undefined);
  }
  read(run:RunHandle,afterCursor:number){
    this.exact(run);return this.journal(()=>this.readBatch(run,afterCursor));
  }
  acknowledge(run:RunHandle,throughCursor:number){this.exact(run);return this.journal(async()=>{
    if(await this.call('ncAcknowledgeContinuousMuxed',{run,throughCursor})!==true)throw Error('Continuous journal ACK unconfirmed.');
    this.acknowledged=throughCursor;});}
  async sealTail(tail:PhysicalTail){this.exact(tail.source.run);return this.mutate(async()=>{
    this.check();const raw=result(await this.call('ncSealContinuousMuxed',{tail}));
    if(raw.kind==='tail_changed')return {kind:'tail_changed'} as const;
    if(raw.kind!=='sealed')throw Error('Invalid continuous native seal.');
    const sealed=parseTail(raw.tail,this.run!);
    if(!sameTailSource(sealed,tail)||sealed.nextRange!==tail.nextRange||sealed.appendRevision!==tail.appendRevision+1)
      throw Error('Continuous sealed tail changed.');
    return {kind:'sealed',tail:sealed} as const;
  });}
  retireSource(source:SourceGrant):Promise<void>{this.exact(source.run);
    const entry=this.entries.get(source.chunkId);if(!entry?.grant||!sameSource(entry.grant,source))throw Error('Continuous muxed source changed.');
    return entry.retiring??=(async()=>{await entry.pump?.catch(error=>{if(!this.stopped)throw error;});
      while(true){const raw=result(await this.call('ncRetireContinuousMuxedSource',{source}));
        if(raw.kind==='closed'){entry.closed=true;return;}if(raw.kind!=='pending')throw Error('Continuous source closure unconfirmed.');await wait();}
    })();
  }
  retireRun(run:RunHandle):Promise<void>{this.exact(run);return this.retiring??=(async()=>{
    await this.serial;await Promise.allSettled([...this.entries.values()].map(e=>e.pump));
    while(true){const raw=result(await this.call('ncRetireContinuousMuxedRun',{run}));
      if(raw.kind==='closed'){
        if(this.visual){
          const snapshot=parseSnapshot(raw.snapshot,run),certificate=snapshot.retirement;
          if(snapshot.state!=='retired'||this.visual.epoch&&!snapshot.visual
            ||snapshot.visual&&(!certificate||!sameSource(certificate.visual.parent,this.visual.parent)
              ||this.visual.epoch&&!sameVisual(certificate.visual,this.visual.epoch)))
            throw Error('Continuous mixed retirement unconfirmed.');
        }
        break;
      }
      if(raw.kind!=='pending')throw Error('Continuous run closure unconfirmed.');await wait();}
    // Final source closure follows whole-run reader joins, never precedes them.
    for(const entry of this.entries.values())if(entry.grant)await this.retireSource(entry.grant);
    for(const entry of this.entries.values())if(entry.stage){
      if(await this.call('ncDropContinuousMuxedStage',{run,stageId:entry.stage})!==true)
        throw Error('Continuous stage closure unconfirmed.');entry.stage=undefined;
      // Unopened staged-only files have no native source to retire.
      entry.closed=true;
    }
    for(const entry of this.entries.values())if(!entry.grant)entry.closed=true;
    if(this.visual?.stage)await this.dropVisualStage(this.visual);
    this.retired=true;this.stopped=true;
  })();}
  invalidate(run:RunHandle,reason:Parameters<ContinuousBufferedAudio['invalidate']>[1]):Promise<void>{
    this.exact(run);if(this.retired)return Promise.resolve();if(this.invalidating)return this.invalidating;this.stopped=true;
    // Invoke the native fence synchronously before awaiting operations/readers.
    const fence=this.call('ncInvalidateContinuousMuxed',{run,reason});
    for(const entry of this.entries.values())entry.abort.abort();
    return this.invalidating=(async()=>{if(await fence!==true)throw Error('Continuous native fence unconfirmed.');
      await Promise.allSettled([this.serial,this.journalSerial,...this.operations]);})();
  }
  async close(){if(this.run){if(!this.retired){await this.invalidate(this.run,'stop');await this.retireRun(this.run);}}
    else if(this.entries.size)throw Error('Continuous muxed run closure unconfirmed.');}
}
