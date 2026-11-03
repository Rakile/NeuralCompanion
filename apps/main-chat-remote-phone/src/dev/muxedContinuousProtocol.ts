import type {AudioChunk} from '../api/types';
import type {MuxedTrialPlan} from './muxedTrialDelivery';

export type RunHandle=Readonly<{id:string;revision:number}>;
export type SourceGrant=Readonly<{run:RunHandle;id:string;chunkId:string;sequenceIndex:number}>;
export type VisualEpoch=Readonly<{run:RunHandle;id:string;parent:SourceGrant}>;
export type ReturnDescriptor=Readonly<{finalSequenceIndex:number;sourceId:string;requestId:string;mediaId:string;
  scopeIdentity:string;motionId:string;sourceFrameCount:number;avatarId:string;
  quality:Readonly<{kbps:number;width:number;fps:24}>;startFrame:number;expiresAtMs:number}>;
export type TailCursor=Readonly<{kind:'speech';source:SourceGrant;nextRange:number;appendRevision:number}>;
export type VisualTail=Readonly<{kind:'visual';source:VisualEpoch;nextRange:number;appendRevision:number}>;
export type PhysicalTail=TailCursor|VisualTail;
export type SourceEvent=Readonly<{cursor:number;run:RunHandle;membership:'speech';source:SourceGrant;
  kind:'source_started'|'source_completed'|'source_readers_closed'|'speech_membership_completed'}>|
  Readonly<{cursor:number;run:RunHandle;membership:'visual';source:VisualEpoch;
    kind:'visual_started'|'visual_readers_closed'|'visual_retired'}>;
export type SourceState=Readonly<{source:SourceGrant;layoutInstalled:boolean;started:boolean;
  completed:boolean;readersClosed:boolean}>;
export type RunSnapshot=Readonly<{version:2;run:RunHandle;
  state:'open'|'sealed'|'drained'|'retired'|'invalidated'|'failed';
  publishedCursor:number;acknowledgedCursor:number;tail:PhysicalTail;speechTail:TailCursor;sources:readonly SourceState[];
  speechMembershipCompleted:boolean;
  visual:Readonly<{epoch:VisualEpoch;started:boolean;readersClosed:boolean;retired:boolean}>|null;
  retirement:Readonly<{mode:'natural'|'forced';run:RunHandle;visual:VisualEpoch;mutationRevision:number}>|null;
  clock?:Readonly<{kind:'speech';source:SourceGrant;seconds:number;playing:boolean;buffering:boolean}>|
    Readonly<{kind:'visual';source:VisualEpoch;seconds:number;playing:boolean;buffering:boolean}>;
  failure?:Readonly<{code:string}>}>;
export type JournalBatch=Readonly<{version:2;events:readonly SourceEvent[];snapshot:RunSnapshot}>;
export type ContinuousMetadata=Readonly<{run:RunHandle;source:SourceGrant;tail:TailCursor}>;
export type ContinuousDescriptor=Readonly<{ticket:string;owner:string;connectionEpoch:string;recoveryEpoch:number;
  replyId:string;chunkId:string;sequenceIndex:number;expiresAtMs:number;mediaId:string;plan:{frames:number;samples:number};
  motionId:string;sourceFrameCount:number;avatarId:string;quality:{kbps:number;width:number;fps:number};
  firstSourceFrame:number;lastSourceFrame:number;idleReturnEntry:number;unsupportedAnticipation:boolean}>;
export type AppendResult=Readonly<{kind:'admitted';source:SourceGrant}>|
  Readonly<{kind:'blocked';reason:'tail_changed'|'future_occupied'|'capacity'}>;

export interface ContinuousBufferedAudio {
  candidate(tail:TailCursor,next:AudioChunk):'pending'|'compatible'|'incompatible';
  finalReturn(tail:TailCursor):Promise<'pending'|'nonfinal'|'admitted'>;
  appendSource(tail:TailCursor,next:AudioChunk,ticket:string,signal:AbortSignal):Promise<AppendResult>;
  subscribe(run:RunHandle,wake:()=>void):()=>void;
  read(run:RunHandle,afterCursor:number):Promise<JournalBatch>;
  acknowledge(run:RunHandle,throughCursor:number):Promise<void>;
  onApplied(event:SourceEvent):void;
  onDrained?(snapshot:RunSnapshot):Promise<void>;
  sealTail(tail:PhysicalTail):Promise<Readonly<{kind:'sealed';tail:PhysicalTail}>|Readonly<{kind:'tail_changed'}>>;
  retireSource(source:SourceGrant):Promise<void>;
  retireRun(run:RunHandle):Promise<void>;
  invalidate(run:RunHandle,reason:'stop'|'skip'|'replacement'|'expiry'|'recovery'|'failure'):Promise<void>;
}

/** The Desktop's existing join conditions, independent of drain/admission.
 * Calling this during preparation cannot seal idle, advance RETURN ownership,
 * select a source, call play, or create an output receipt.
 */
export function compatibleMuxedPlans(a:MuxedTrialPlan,b:MuxedTrialPlan):boolean {
  const first=b.timeline.sourceIndices[0],last=a.timeline.sourceIndices.at(-1),count=a.timeline.sourceFrameCount;
  if(!Number.isSafeInteger(count)||count<1||first===undefined||last===undefined
    ||!Number.isSafeInteger(first)||!Number.isSafeInteger(last)||first<0||first>=count||last<0||last>=count)
    return false;
  return !b.anticipation&&a.timeline.motionId===b.timeline.motionId&&count===b.timeline.sourceFrameCount
    &&a.timeline.sourceFps===24&&b.timeline.sourceFps===24&&a.idleReturn.avatarId===b.idleReturn.avatarId
    &&a.idleReturn.videoQuality.video_kbps===b.idleReturn.videoQuality.video_kbps
    &&a.idleReturn.videoQuality.video_width===b.idleReturn.videoQuality.video_width
    &&a.idleReturn.videoQuality.video_fps===24&&b.idleReturn.videoQuality.video_fps===24
    &&first===(last+1)%count&&a.idleReturn.startFrame===first;
}

function invalid():never {throw Error('Invalid continuous native response.');}
function row(value:unknown):Record<string,unknown> {
  if(!value||typeof value!=='object'||Array.isArray(value))return invalid();
  return value as Record<string,unknown>;
}
function integer(value:unknown,min:number,max=Number.MAX_SAFE_INTEGER):number {
  if(typeof value!=='number'||!Number.isSafeInteger(value)||value<min||value>max)return invalid();
  return value;
}
function id(value:unknown):string {
  if(typeof value!=='string'||!/^[A-Za-z0-9_.-]{1,128}$/.test(value))return invalid();
  return value;
}
function bool(value:unknown):boolean {if(typeof value!=='boolean')return invalid();return value;}
export function sameRun(a:RunHandle,b:RunHandle):boolean {return a.id===b.id&&a.revision===b.revision;}
export function sameSource(a:SourceGrant,b:SourceGrant):boolean {
  return sameRun(a.run,b.run)&&a.id===b.id&&a.chunkId===b.chunkId&&a.sequenceIndex===b.sequenceIndex;
}
export function parseRunHandle(value:unknown,expected?:RunHandle):RunHandle {
  const raw=row(value),run=Object.freeze({id:id(raw.id),revision:integer(raw.revision,1)});
  if(expected&&!sameRun(run,expected))return invalid();
  return run;
}
export function parseSourceGrant(value:unknown,expected:RunHandle):SourceGrant {
  const raw=row(value);
  return Object.freeze({run:parseRunHandle(raw.run,expected),id:id(raw.id),chunkId:id(raw.chunkId),
    sequenceIndex:integer(raw.sequenceIndex,0,63)});
}
export function sameVisual(a:VisualEpoch,b:VisualEpoch):boolean {
  return sameRun(a.run,b.run)&&a.id===b.id&&sameSource(a.parent,b.parent);
}
export function sameTailSource(a:PhysicalTail,b:PhysicalTail):boolean {
  return a.kind==='speech'?b.kind==='speech'&&sameSource(a.source,b.source)
    :b.kind==='visual'&&sameVisual(a.source,b.source);
}
export function parseVisualEpoch(value:unknown,run:RunHandle):VisualEpoch {
  const raw=row(value),parent=parseSourceGrant(raw.parent,run),epochId=id(raw.id);
  if(epochId===parent.id)return invalid();
  return Object.freeze({run:parseRunHandle(raw.run,run),id:epochId,parent});
}
export function parseTail(value:unknown,run:RunHandle):PhysicalTail {
  const raw=row(value);
  const appendRevision=integer(raw.appendRevision,1);
  if(raw.kind==='speech')return Object.freeze({kind:'speech',source:parseSourceGrant(raw.source,run),
    nextRange:integer(raw.nextRange,1,60),appendRevision});
  if(raw.kind==='visual')return Object.freeze({kind:'visual',source:parseVisualEpoch(raw.source,run),
    nextRange:integer(raw.nextRange,1,10006),appendRevision});
  return invalid();
}
/** Native owns the last installed range; JS owns the next append cursor. */
export function parseNativeTail(value:unknown,run:RunHandle):PhysicalTail {
  const raw=row(value);
  if(raw.kind!=='speech'&&raw.kind!=='visual')return invalid();
  integer(raw.ordinal,0,raw.kind==='speech'?3839:13845);
  return parseTail({kind:raw.kind,source:raw.source,nextRange:integer(raw.lastRange,0,raw.kind==='speech'?59:10005)+1,
    appendRevision:integer(raw.mutationRevision,1)},run);
}
export function parseAppendResult(value:unknown,run:RunHandle):AppendResult {
  const raw=row(value);
  if(raw.kind==='admitted')return Object.freeze({kind:'admitted',source:parseSourceGrant(raw.source,run)});
  if(raw.kind==='blocked'&&(raw.reason==='tail_changed'||raw.reason==='future_occupied'||raw.reason==='capacity'))
    return Object.freeze({kind:'blocked',reason:raw.reason});
  return invalid();
}
export function parseSnapshot(value:unknown,expected:RunHandle):RunSnapshot {
  const raw=row(value),run=parseRunHandle(raw.run,expected);
  if(raw.version!==2)return invalid();
  const state=raw.state;
  if(state!=='open'&&state!=='sealed'&&state!=='drained'&&state!=='retired'&&state!=='invalidated'&&state!=='failed')
    return invalid();
  const publishedCursor=integer(raw.publishedCursor,0,256);
  const acknowledgedCursor=integer(raw.acknowledgedCursor,0,publishedCursor);
  if(!Array.isArray(raw.sources)||raw.sources.length<1||raw.sources.length>64)return invalid();
  const sources:SourceState[]=raw.sources.map(value=>{
    const entry=row(value),source=parseSourceGrant(entry.source,run);
    const layoutInstalled=bool(entry.layoutInstalled),started=bool(entry.started),
      completed=bool(entry.completed),readersClosed=bool(entry.readersClosed);
    if(completed&&(!started||!layoutInstalled))return invalid();
    return Object.freeze({source,layoutInstalled,started,completed,readersClosed});
  });
  if(new Set(sources.map(x=>x.source.id)).size!==sources.length
    ||new Set(sources.map(x=>x.source.chunkId)).size!==sources.length
    ||sources.some((entry,i)=>i>0&&entry.source.sequenceIndex!==sources[i-1]!.source.sequenceIndex+1))
    return invalid();
  const find=(grant:SourceGrant)=>sources.find(x=>sameSource(x.source,grant));
  const tail=parseTail(raw.tail,run),speechTail=parseTail(raw.speechTail,run);
  if(speechTail.kind!=='speech')return invalid();
  const tailSource=find(speechTail.source);
  if(!tailSource)return invalid();
  const pending=sources.filter(x=>x.source.sequenceIndex>speechTail.source.sequenceIndex);
  if(pending.length>1||pending.some(x=>x.layoutInstalled||x.started||x.completed)
    ||pending.length>0&&(state==='sealed'||state==='drained'))return invalid();
  if((state==='sealed'||state==='drained')&&!tailSource.layoutInstalled)return invalid();
  if(state==='drained'&&sources.some(x=>!x.completed)||state==='retired'&&sources.some(x=>!x.readersClosed))
    return invalid();
  const speechMembershipCompleted=bool(raw.speechMembershipCompleted);
  let visual:RunSnapshot['visual']=null;
  if(raw.visual!==null){
    const entry=row(raw.visual),epoch=parseVisualEpoch(entry.epoch,run);
    const started=bool(entry.started),readersClosed=bool(entry.readersClosed),retired=bool(entry.retired);
    if(!sameSource(epoch.parent,speechTail.source)||!sameSource(epoch.parent,sources.at(-1)!.source)
      ||sources.some(x=>!x.layoutInstalled)||sources.some(x=>x.source.id===epoch.id)
      ||started&&!speechMembershipCompleted||readersClosed&&state==='open'||retired&&!readersClosed)return invalid();
    visual=Object.freeze({epoch,started,readersClosed,retired});
  }
  if(publishedCursor>sources.length*3+(visual?4:0))return invalid();
  if(tail.kind==='visual'){
    if(!visual||!sameVisual(tail.source,visual.epoch)||tail.nextRange<2)return invalid();
  }else if(!sameSource(tail.source,speechTail.source)||tail.nextRange!==speechTail.nextRange
    ||tail.appendRevision!==speechTail.appendRevision)return invalid();
  if(tail.appendRevision!==speechTail.appendRevision
    ||speechMembershipCompleted&&(!visual||tail.kind!=='visual'||sources.some(x=>!x.completed)))return invalid();
  let failure:RunSnapshot['failure'];
  if(raw.failure!==undefined&&raw.failure!==null)failure=Object.freeze({code:id(row(raw.failure).code)});
  if(state==='failed'&&!failure)return invalid();
  let retirement:RunSnapshot['retirement']=null;
  if(raw.retirement!==null){
    const entry=row(raw.retirement),mode=entry.mode,epoch=parseVisualEpoch(entry.visual,run);
    if(mode!=='natural'&&mode!=='forced'||!visual||!visual.retired||!visual.readersClosed
      ||state!=='retired'||!sameVisual(epoch,visual.epoch)
      ||mode==='natural'&&(tail.kind!=='visual'||!speechMembershipCompleted||sources.some(x=>!x.completed)||failure)
      ||mode==='forced'&&(!failure||tail.kind==='speech'&&(visual.started||speechMembershipCompleted)))return invalid();
    const mutationRevision=integer(entry.mutationRevision,1);
    if(mutationRevision!==tail.appendRevision)return invalid();
    retirement=Object.freeze({mode,run:parseRunHandle(entry.run,run),visual:epoch,mutationRevision});
  }
  if(visual?.retired&&!retirement)return invalid();
  let clock:RunSnapshot['clock'];
  if(raw.clock!==undefined&&raw.clock!==null){
    const entry=row(raw.clock),seconds=entry.seconds,playing=bool(entry.playing),buffering=bool(entry.buffering);
    if(typeof seconds!=='number'||!Number.isFinite(seconds)||seconds<0||seconds>120
      ||playing&&(state==='drained'||state==='retired'||state==='invalidated'||state==='failed'))return invalid();
    if(entry.kind==='speech'){
      const source=parseSourceGrant(entry.source,run),owned=find(source);
      if(!owned||!owned.started||playing&&(owned.completed||speechMembershipCompleted))return invalid();
      clock=Object.freeze({kind:'speech',source,seconds,playing,buffering});
    }else if(entry.kind==='visual'){
      const source=parseVisualEpoch(entry.source,run);
      if(!visual||!visual.started||!speechMembershipCompleted||!sameVisual(source,visual.epoch)
        ||playing&&(visual.readersClosed||visual.retired))return invalid();
      clock=Object.freeze({kind:'visual',source,seconds,playing,buffering});
    }else return invalid();
  }
  return Object.freeze({version:2,run,state,publishedCursor,acknowledgedCursor,tail,speechTail,
    sources:Object.freeze(sources),speechMembershipCompleted,visual,retirement,
    ...(clock?{clock}:{}),...(failure?{failure}:{})});
}
/** Copied protocol2 observation only. Epoch lifecycle is never a speech receipt. */
export function parseJournalBatch(value:unknown,run:RunHandle,afterCursor:number):JournalBatch {
  integer(afterCursor,0,256);
  const raw=row(value);
  if(raw.version!==2)return invalid();
  const snapshot=parseSnapshot(raw.snapshot,run);
  if(afterCursor<snapshot.acknowledgedCursor||afterCursor>snapshot.publishedCursor
    ||!Array.isArray(raw.events)||raw.events.length!==snapshot.publishedCursor-afterCursor)return invalid();
  const kinds=new Set<string>();
  const events:SourceEvent[]=raw.events.map((value,index)=>{
    const entry=row(value),eventRun=parseRunHandle(entry.run,run),cursor=integer(entry.cursor,1,256),kind=entry.kind;
    if(cursor!==afterCursor+index+1)return invalid();
    let event:SourceEvent;
    if(entry.membership==='visual'){
      const source=parseVisualEpoch(entry.source,run),owned=snapshot.visual;
      if(!owned||!sameVisual(source,owned.epoch)
        ||kind!=='visual_started'&&kind!=='visual_readers_closed'&&kind!=='visual_retired'
        ||kind==='visual_started'&&!owned.started||kind==='visual_readers_closed'&&!owned.readersClosed
        ||kind==='visual_retired'&&!owned.retired)return invalid();
      event=Object.freeze({cursor,run:eventRun,membership:'visual',source,kind});
    }else if(entry.membership==='speech'){
      const source=parseSourceGrant(entry.source,run),owned=snapshot.sources.find(x=>sameSource(x.source,source));
      if(!owned||kind!=='source_started'&&kind!=='source_completed'&&kind!=='source_readers_closed'
        &&kind!=='speech_membership_completed'
        ||kind==='source_started'&&!owned.started||kind==='source_completed'&&!owned.completed
        ||kind==='source_readers_closed'&&!owned.readersClosed
        ||kind==='speech_membership_completed'&&(!snapshot.speechMembershipCompleted
          ||!sameSource(source,snapshot.speechTail.source)))return invalid();
      event=Object.freeze({cursor,run:eventRun,membership:'speech',source,kind});
    }else return invalid();
    const unique=event.source.id+':'+kind;
    if(kinds.has(unique))return invalid();kinds.add(unique);return event;
  });
  for(const event of events){
    const earlier=(kind:SourceEvent['kind'])=>events.some(x=>x.source.id===event.source.id&&x.kind===kind&&x.cursor<event.cursor);
    const later=(kind:SourceEvent['kind'])=>events.some(x=>x.source.id===event.source.id&&x.kind===kind&&x.cursor>event.cursor);
    if(event.membership==='visual'){
      if(event.kind==='visual_started'&&earlier('visual_readers_closed')
        ||event.kind==='visual_started'&&events.some(x=>x.membership==='speech'
          &&sameSource(x.source,event.source.parent)&&x.kind==='speech_membership_completed'&&x.cursor>event.cursor)
        ||event.kind==='visual_retired'&&later('visual_readers_closed'))return invalid();
    }else {
      if(event.kind==='source_started'&&earlier('source_completed')
        ||event.kind==='speech_membership_completed'&&later('source_completed'))return invalid();
      if(event.kind==='source_started'&&snapshot.sources.some(x=>x.source.sequenceIndex<event.source.sequenceIndex
        &&(!x.completed||events.some(e=>e.membership==='speech'&&sameSource(e.source,x.source)
          &&e.kind==='source_completed'&&e.cursor>event.cursor))))return invalid();
    }
  }
  return Object.freeze({version:2,events:Object.freeze(events),snapshot});
}
