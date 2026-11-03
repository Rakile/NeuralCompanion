import {diagnosticErrorOrigin} from '../utils/diagnosticErrorOrigin';
import {captureControlTrail} from '../diagnostics/captureControlTrail';
import {cleanupFailureOperations} from '../utils/cleanupFailureProvenance';

export function orderedPlaybackErrorMessage(reason:string):string {
  return reason==='ordered_gpu_encode_failed'
    ?'Desktop GPU H.264 encoding failed. NVIDIA NVENC is required. Check the NVIDIA driver and FFmpeg setup; see the Main Chat Remote GPU encoding setup guide.'
    :reason;
}

/** Error-only evidence. Preserve protocol field paths and bundle coordinates,
 * never arbitrary native exception messages, file paths or credentials. */
export function orderedFailureDetails(error:unknown){
  let reason='ordered.unclassified_failure',errorClass='opaque';
  let nativeFailure:Record<string,string>|undefined;
  try{if(error instanceof Error){
    if(['Error','TypeError','RangeError','SyntaxError'].includes(error.name))errorClass=error.name;
    const message=error.message;
    const wrapped=/^Call to function 'AudioPlayer\.(nc(?:Open|Stage|Append|Read|Fence|Close|Invalidate)OrderedMuxed|nc(?:Prepare|Arm|Read|Close)OrderedCached|ncCloseMuxedTrial)' has been rejected\.(?=\r?\n|$)/.exec(message);
    if(wrapped){
      // Expo can reject before the native RPC body and supplies a decorated
      // message without a Java exception-class prefix. Keep the known method
      // even then; never copy the arbitrary cause text into the log.
      const cause=/^\r?\n→ Caused by: java\.lang\.(IllegalArgumentException|IllegalStateException): ([^\r\n]+)$/.exec(message.slice(wrapped[0].length));
      nativeFailure={method:wrapped[1]!,exception_class:cause?.[1]??'unavailable',
        reason:cause&&/^ordered_[a-z_]{1,96}$/.test(cause[2]!)?cause[2]!:'filtered'};
      // These codes are defined by the installed Expo CodedException classes.
      // Project to a finite kind (not a sensitive generic 'code' field) so the
      // existing phone sanitizer preserves it. Accessors are never invoked.
      const code=Object.getOwnPropertyDescriptor(error,'code')?.value;
      const kinds:Record<string,string>={ERR_USING_RELEASED_SHARED_OBJECT:'using_released_shared_object',
        ERR_INVALID_SHARED_OBJECT_ID:'invalid_shared_object_id',ERR_INVALID_SHARED_OBJECT_TYPE:'invalid_shared_object_type'};
      if(typeof code==='string'&&Object.prototype.hasOwnProperty.call(kinds,code))nativeFailure.kind=kinds[code]!;
    }
    if(/^(?:ordered[._]|output_|phone_reply_)[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$/.test(message)&&message.length<=160)reason=message;
    else switch(message){
      case 'Buffered media descriptor length or content type mismatch.':reason='ordered.media_descriptor_mismatch';break;
      case 'NC peer request timed out.':reason='ordered.peer_timeout';break;
      case 'NC peer request cancelled.':reason='ordered.peer_cancelled';break;
      case 'Peer media unavailable.':reason='ordered.media_unavailable';break;
      case 'Peer media cancelled.':reason='ordered.media_cancelled';break;
      case 'Buffered media cleanup remains unconfirmed.':reason='ordered.media_cleanup_unconfirmed';break;
      case 'Idle inventory unavailable.':reason='ordered.idle_inventory_unavailable';break;
      case 'Idle range unavailable.':reason='ordered.idle_range_unavailable';break;
    }
  }}catch{}
  // Only enumerated failure-time transport evidence; never the request, auth,
  // scope identifier or arbitrary exception properties.
  let transport:Record<string,string|boolean|number>|undefined;
  try{
    const value=(error as {orderedTransport?:Record<string,unknown>})?.orderedTransport;
    if(value&&['open','recover','wait','started','ack','halt','restart','close'].includes(String(value.operation))
      &&['before_request','after_response'].includes(String(value.stage))
      &&['missing_peer','closed_peer','scope_changed','runtime_not_current','http_rejected'].includes(String(value.condition))){
      transport={operation:String(value.operation),stage:String(value.stage),condition:String(value.condition)};
      for(const key of ['cleanup','peer_present','peer_closed','scope_matches'])if(typeof value[key]==='boolean')transport[key]=value[key] as boolean;
      if(value.condition==='http_rejected'){
        if(Number.isInteger(value.http_status)&&Number(value.http_status)>=100&&Number(value.http_status)<=599)
          transport.http_status=Number(value.http_status);
        if(Number.isSafeInteger(value.elapsed_ms)&&Number(value.elapsed_ms)>=0)transport.elapsed_ms=Number(value.elapsed_ms);
        if(['missing','accepted','filtered'].includes(String(value.reason_state)))transport.reason_state=String(value.reason_state);
      }
    }
  }catch{}
  let idleTransfer:Record<string,string|number>|undefined;
  try{
    const value=error&&typeof error==='object'?Object.getOwnPropertyDescriptor(error,'idleTransfer')?.value:undefined;
    if(value&&['manifest','range'].includes(value.stage)&&Number.isInteger(value.http_status)
      &&value.http_status>=100&&value.http_status<=599&&Number.isSafeInteger(value.received_bytes)
      &&value.received_bytes>=0&&value.received_bytes<=128*1024&&Number.isSafeInteger(value.expected_bytes)
      &&value.expected_bytes>=0&&value.expected_bytes<=24576)
      idleTransfer={stage:value.stage,http_status:value.http_status,received_bytes:value.received_bytes,expected_bytes:value.expected_bytes};
  }catch{}
  const cleanupOperations=cleanupFailureOperations(error);
  return {reason,error_class:errorClass,error_origin:diagnosticErrorOrigin(error),capture_actions:captureControlTrail(),
    ...(cleanupOperations.length?{cleanup_operations:cleanupOperations}:{}),
    ...(nativeFailure?{native_failure:nativeFailure}:{}),...(idleTransfer?{idle_transfer:idleTransfer}:{}),...(transport?{transport}:{})};
}

/** Desktop owns frame order. These immutable labels describe media; none of
 * them is an output grant, a speech receipt or evidence that a reader closed. */
export type OrderedKind='idle'|'transition'|'speech';
export type OrderedFrame=Readonly<{sourceId:string;frame:number;sourceFrameCount:number}>;
export type OrderedChunk=Readonly<{version:1;streamId:string;generation:number;ordinal:number;predecessor:number|null;
  kind:OrderedKind;sourceId:string;sourceRange:Readonly<{start:number;totalFrames:number;frames:readonly OrderedFrame[]}>;
  mediaId:string;frameCount:number;fps:24;sampleCount:number;replyId:string|null;sequenceIndex:number|null;sha256:string;byteLength:number}>;
export type OrderedSource=Readonly<{kind:OrderedKind;sourceId:string;replyId:string|null;sequenceIndex:number|null;mediaId:string;
  plan:Readonly<{frames:number;samples:number}>;firstOrdinal:number}>;
export type OrderedFile=Readonly<{path:string;index:number;startFrame:number;frameCount:number;validSamples:number;
  delaySamples:number;paddingSamples:number;rawSamples:number;sampleRate:48000;fps:24}>;
export type OrderedAnnouncement=Readonly<{chunk:OrderedChunk;source:OrderedSource;file:OrderedFile}>;
export type OrderedRun=Readonly<{id:string;revision:number}>;
export type OrderedStoppedOutput=Readonly<{version:1;streamId:string;generation:number}&(
  {known:true;ordinal:number;frameOffset:number;provenance:'codec_surface'}|{known:false;reason:string})>;
export type OrderedNativeSource=Readonly<{id:string;sourceId:string;kind:OrderedKind;replyId:string|null;sequenceIndex:number|null;
  firstOrdinal:number;rangeCount:number;started:boolean;completed:boolean;readersClosed:boolean}>;
export type OrderedNativeSnapshot=Readonly<{version:1;run:OrderedRun;streamId:string;generation:number;state:string;nextOrdinal:number;
  mutationRevision:number;publishedCursor:number;acknowledgedCursor:number;readersClosedThrough:number;failure:string|null;
  sources:readonly OrderedNativeSource[]}>;

function requireValue(valid:unknown,field:string):asserts valid {if(!valid)throw Error('ordered.'+field);}
function object(value:unknown,keys:readonly string[],field:string):Record<string,unknown>{
  requireValue(value!==null&&typeof value==='object'&&!Array.isArray(value),field+'.object');
  const row=value as Record<string,unknown>;
  requireValue(Object.keys(row).length===keys.length&&keys.every(key=>Object.prototype.hasOwnProperty.call(row,key)),field+'.fields');
  return row;
}
function integer(value:unknown,field:string,min=0,max=Number.MAX_SAFE_INTEGER):number{
  requireValue(typeof value==='number'&&Number.isSafeInteger(value)&&value>=min&&value<=max,field);return value;
}
function identity(value:unknown,field:string,max=160):string{
  requireValue(typeof value==='string'&&value.length<=max&&/^[A-Za-z0-9_-]+$/.test(value),field);return value;
}
function hex(value:unknown,field:string,size:number):string{
  requireValue(typeof value==='string'&&value.length===size&&/^[a-f0-9]+$/.test(value),field);return value;
}
function kind(value:unknown,field:string):OrderedKind{
  requireValue(value==='idle'||value==='transition'||value==='speech',field);return value;
}
export function parseOrderedStoppedOutput(value:unknown):OrderedStoppedOutput {
  const known=(value as {known?:unknown}|null)?.known;
  requireValue(typeof known==='boolean','stopped.known');
  const r=object(value,known?['version','streamId','generation','known','ordinal','frameOffset','provenance']
    :['version','streamId','generation','known','reason'],'stopped');
  requireValue(r.version===1,'stopped.version');
  const common={version:1 as const,streamId:hex(r.streamId,'stopped.streamId',32),generation:integer(r.generation,'stopped.generation')};
  if(known){
    requireValue(r.provenance==='codec_surface','stopped.provenance');
    return Object.freeze({...common,known:true,ordinal:integer(r.ordinal,'stopped.ordinal'),
      frameOffset:integer(r.frameOffset,'stopped.frameOffset',0,11),provenance:'codec_surface'});
  }
  requireValue(typeof r.reason==='string'&&['no_rendered_frame','render_callback_pending','render_callback_capacity',
    'frame_pts_unmapped','render_callback_unmapped','render_callback_ambiguous','codec_owner_changed_pending',
    'render_listener_unavailable','render_pts_reused','render_release_failed','codec_reset_pending','render_listener_missing',
    'render_source_released'].includes(r.reason),'stopped.reason');
  return Object.freeze({...common,known:false,reason:r.reason});
}
export function parseOrderedChunk(value:unknown):OrderedChunk {
  const r=object(value,['version','streamId','generation','ordinal','predecessor','kind','sourceId','sourceRange',
    'mediaId','frameCount','fps','sampleCount','replyId','sequenceIndex','sha256','byteLength'],'chunk');
  requireValue(r.version===1,'chunk.version');
  const ordinal=integer(r.ordinal,'chunk.ordinal'),type=kind(r.kind,'chunk.kind');
  const range=object(r.sourceRange,['start','totalFrames','frames'],'chunk.sourceRange');
  const totalFrames=integer(range.totalFrames,'chunk.totalFrames',1),start=integer(range.start,'chunk.start',0,totalFrames-1);
  requireValue(Array.isArray(range.frames)&&range.frames.length===Math.min(12,totalFrames-start),'chunk.frames');
  const frames=Object.freeze(range.frames.map((value,index)=>{
    const row=object(value,['sourceId','frame','sourceFrameCount'],`chunk.frame.${index}`);
    const sourceFrameCount=integer(row.sourceFrameCount,`chunk.frame.${index}.count`,1);
    return Object.freeze({sourceId:identity(row.sourceId,`chunk.frame.${index}.sourceId`),
      frame:integer(row.frame,`chunk.frame.${index}.frame`,0,sourceFrameCount-1),sourceFrameCount});
  }));
  const frameCount=integer(r.frameCount,'chunk.frameCount',1,12),sampleCount=integer(r.sampleCount,'chunk.sampleCount',1,25999);
  requireValue(frameCount===frames.length&&r.fps===24,'chunk.frames_fps');
  requireValue(r.predecessor===(ordinal===0?null:ordinal-1),'chunk.predecessor');
  const replyId=type==='speech'?identity(r.replyId,'chunk.replyId'):null;
  const sequenceIndex=type==='speech'?integer(r.sequenceIndex,'chunk.sequenceIndex'):null;
  if(type==='speech')requireValue(Math.abs(sampleCount-frameCount*2000)<2000
    &&(start+frameCount===totalFrames||sampleCount===frameCount*2000),'chunk.audio_range');
  else requireValue(r.replyId===null&&r.sequenceIndex===null&&sampleCount===frameCount*2000,'chunk.visual');
  return Object.freeze({version:1,streamId:hex(r.streamId,'chunk.streamId',32),generation:integer(r.generation,'chunk.generation'),
    ordinal,predecessor:ordinal===0?null:ordinal-1,kind:type,sourceId:identity(r.sourceId,'chunk.sourceId'),
    sourceRange:Object.freeze({start,totalFrames,frames}),mediaId:hex(r.mediaId,'chunk.mediaId',32),frameCount,fps:24,
    sampleCount,replyId,sequenceIndex,sha256:hex(r.sha256,'chunk.sha256',64),byteLength:integer(r.byteLength,'chunk.byteLength',1,16*1024*1024)});
}
export function parseOrderedAnnouncement(value:unknown):OrderedAnnouncement {
  const row=object(value,['chunk','source','file'],'announcement'),chunk=parseOrderedChunk(row.chunk);
  const s=object(row.source,['kind','sourceId','replyId','sequenceIndex','mediaId','plan','firstOrdinal'],'source');
  const p=object(s.plan,['frames','samples'],'source.plan');
  const plan=Object.freeze({frames:integer(p.frames,'source.frames',1,720),samples:integer(p.samples,'source.samples',1,1441999)});
  const source=Object.freeze({kind:kind(s.kind,'source.kind'),sourceId:identity(s.sourceId,'source.sourceId',128),
    replyId:s.replyId===null?null:identity(s.replyId,'source.replyId',128),
    sequenceIndex:s.sequenceIndex===null?null:integer(s.sequenceIndex,'source.sequenceIndex',0,63),mediaId:hex(s.mediaId,'source.mediaId',32),
    plan,firstOrdinal:integer(s.firstOrdinal,'source.firstOrdinal')});
  const index=chunk.sourceRange.start/12;
  requireValue(Number.isSafeInteger(index)&&chunk.ordinal-index===source.firstOrdinal,'source.ordinal');
  requireValue(source.kind===chunk.kind&&source.sourceId===chunk.sourceId&&source.replyId===chunk.replyId
    &&source.sequenceIndex===chunk.sequenceIndex&&source.mediaId===chunk.mediaId&&plan.frames===chunk.sourceRange.totalFrames,'source.binding');
  requireValue(Math.abs(plan.samples-plan.frames*2000)<2000&&(source.kind==='speech'||plan.samples===plan.frames*2000),'source.samples');
  const expectedSamples=Math.min(24000,plan.samples-index*24000);
  // A full terminal 12-frame clip can also contain the sub-frame AAC residual.
  requireValue(chunk.sampleCount===(index===Math.ceil(plan.frames/12)-1?plan.samples-index*24000:expectedSamples),'source.range_samples');
  const f=object(row.file,['path','index','startFrame','frameCount','validSamples','delaySamples','paddingSamples','rawSamples','sampleRate','fps'],'file');
  const route=`/api/remote-output/media/${chunk.streamId}/${chunk.generation}/${chunk.ordinal}.mp4`;
  requireValue(f.path===route,'file.route');
  requireValue(f.index===index&&f.startFrame===chunk.sourceRange.start&&f.frameCount===chunk.frameCount
    &&f.validSamples===chunk.sampleCount&&f.sampleRate===48000&&f.fps===24,'file.binding');
  const delaySamples=integer(f.delaySamples,'file.delaySamples',0,2048),paddingSamples=integer(f.paddingSamples,'file.paddingSamples',0,1023);
  const rawSamples=integer(f.rawSamples,'file.rawSamples',1024,28672);
  requireValue(rawSamples%1024===0&&rawSamples-delaySamples-paddingSamples===chunk.sampleCount,'file.trim');
  return Object.freeze({chunk,source,file:Object.freeze({path:route,index,startFrame:chunk.sourceRange.start,frameCount:chunk.frameCount,
    validSamples:chunk.sampleCount,delaySamples,paddingSamples,rawSamples,sampleRate:48000,fps:24})});
}
export function parseOrderedNativeSnapshot(value:unknown):OrderedNativeSnapshot {
  const r=object(value,['version','run','streamId','generation','state','nextOrdinal','mutationRevision','publishedCursor',
    'acknowledgedCursor','readersClosedThrough','failure','sources'],'native');
  const run=object(r.run,['id','revision'],'native.run'),nextOrdinal=integer(r.nextOrdinal,'native.nextOrdinal');
  requireValue(r.version===1&&typeof r.state==='string'&&['open','sealed','drained','invalidated','failed','retired'].includes(r.state),'native.state');
  requireValue(r.failure===null||typeof r.failure==='string'&&/^[A-Za-z0-9_.-]{1,160}$/.test(r.failure),'native.failure');
  const publishedCursor=integer(r.publishedCursor,'native.publishedCursor'),acknowledgedCursor=integer(r.acknowledgedCursor,'native.acknowledgedCursor',0,publishedCursor);
  const readersClosedThrough=integer(r.readersClosedThrough,'native.readersClosedThrough',-1,nextOrdinal-1);
  requireValue(Array.isArray(r.sources)&&r.sources.length<=64,'native.sources');
  const seen=new Set<string>();
  const sources=Object.freeze(r.sources.map(value=>{
    const s=object(value,['id','sourceId','kind','replyId','sequenceIndex','firstOrdinal','rangeCount','started','completed','readersClosed'],'native.source');
    const id=identity(s.id,'native.source.id',128),type=kind(s.kind,'native.source.kind');
    requireValue(!seen.has(id),'native.source.duplicate');seen.add(id);
    for(const key of ['started','completed','readersClosed'])requireValue(typeof s[key]==='boolean','native.source.'+key);
    const replyId=type==='speech'?identity(s.replyId,'native.source.replyId',128):null;
    const sequenceIndex=type==='speech'?integer(s.sequenceIndex,'native.source.sequenceIndex',0,63):null;
    if(type!=='speech')requireValue(s.replyId===null&&s.sequenceIndex===null,'native.source.visual');
    // Native grants precede the asynchronous timeline mutation. After a fence,
    // that real membership can survive without a committed range. It proves
    // custody/admission only, never playback or an advancement of nextOrdinal.
    const pending=['invalidated','failed','retired'].includes(r.state as string)
      &&s.started===false&&s.completed===false;
    return Object.freeze({id,sourceId:identity(s.sourceId,'native.source.sourceId',128),kind:type,replyId,sequenceIndex,
      firstOrdinal:integer(s.firstOrdinal,'native.source.firstOrdinal',0,pending?nextOrdinal:nextOrdinal-1),rangeCount:integer(s.rangeCount,'native.source.rangeCount',1,60),
      started:s.started as boolean,completed:s.completed as boolean,readersClosed:s.readersClosed as boolean});
  }));
  return Object.freeze({version:1,run:Object.freeze({id:identity(run.id,'native.run.id',128),revision:integer(run.revision,'native.run.revision',1)}),
    streamId:hex(r.streamId,'native.streamId',32),generation:integer(r.generation,'native.generation'),state:r.state,
    nextOrdinal,mutationRevision:integer(r.mutationRevision,'native.mutationRevision'),publishedCursor,acknowledgedCursor,
    readersClosedThrough,failure:r.failure as string|null,sources});
}
