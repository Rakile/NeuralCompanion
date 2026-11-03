import {parseVideoQuality} from '../relay/idleLoopCache';
import type {VideoQuality} from '../relay/idleLoopCache';
import type {SourceTimeline} from '../relay/frameHandoff';
export type IdleChunkReturn={version:1;sourceId:string;mediaId:string;audio:{id:string;phone_request_id:string;url_path:string};
  motionId:string;avatarId:string;sourceFrameCount:number;fps:24;startFrame:number;continuationReady:true;videoQuality:VideoQuality};
export type IdleChunkRow={index:number;startFrame:number;frameCount:12;sourceIndices:number[];state:'ready'|'pending';uri?:string;bytes?:number;sha256?:string};
export type IdleChunkWaitingPlan={version:1;planId:string;firstIndex:number;sourceIndices:number[]};
export type IdleChunkWaitingAuthority=Omit<IdleChunkWaitingPlan,'version'>&{avatarId:string;sourceFrameCount:number};
export type IdleChunkStatus={trialId:string;requestId:string;version:1;mediaId:string;motionId:string;avatarId:string;
  sourceFrameCount:number;fps:24;startFrame:number;cursor:number;videoQuality:VideoQuality;segments:IdleChunkRow[];waitingPlan?:IdleChunkWaitingPlan};
const object=(value:unknown):value is Record<string,any>=>Boolean(value)&&typeof value==='object'&&!Array.isArray(value);
const integer=(value:unknown,low:number,high:number):value is number=>Number.isSafeInteger(value)&&Number(value)>=low&&Number(value)<=high;
const id=(value:unknown,length:number):value is string=>typeof value==='string'&&new RegExp(`^[a-f0-9]{${length}}$`).test(value);
export function parseIdleChunkReturn(raw:unknown,mediaId:string,audio:IdleChunkReturn['audio'],timeline:SourceTimeline):IdleChunkReturn {
  const invalid=()=>{throw Error('Invalid idle chunk return.');};
  const last=timeline.sourceIndices[timeline.sourceIndices.length-1];
  if(!object(raw)||Object.keys(raw).sort().join(',')!=='audio,avatarId,continuationReady,fps,mediaId,motionId,sourceFrameCount,sourceId,startFrame,version,videoQuality'
    ||raw.version!==1||!id(raw.sourceId,32)||!id(mediaId,32)||raw.mediaId!==mediaId||!id(raw.motionId,64)
    ||raw.motionId!==timeline.motionId||raw.sourceFrameCount!==timeline.sourceFrameCount||raw.fps!==24
    ||typeof raw.avatarId!=='string'||raw.avatarId.length<1||raw.avatarId.length>256||raw.continuationReady!==true
    ||!integer(raw.startFrame,0,timeline.sourceFrameCount-1)
    ||last===undefined||raw.startFrame!==(last+1)%timeline.sourceFrameCount
    ||!object(raw.audio)||Object.keys(raw.audio).sort().join(',')!=='id,phone_request_id,url_path'
    ||Object.keys(audio).some(key=>raw.audio[key]!==audio[key as keyof typeof audio]))return invalid();
  return {version:1,sourceId:raw.sourceId,mediaId,audio:{...audio},motionId:raw.motionId,avatarId:raw.avatarId,
    sourceFrameCount:raw.sourceFrameCount,fps:24,startFrame:raw.startFrame,continuationReady:true,
    videoQuality:parseVideoQuality(raw.videoQuality)};
}
export function parseIdleChunkStatus(raw:unknown,trialId:string,requestId:string,authority?:IdleChunkWaitingAuthority):IdleChunkStatus|null {
  const invalid=()=>{throw Error('Invalid idle chunk status.');};
  if(!id(trialId,32)||!id(requestId,32)||!object(raw)||raw.trialId!==trialId||raw.requestId!==requestId) return invalid();
  if(raw.state==='unavailable')throw Error('Idle chunk producer unavailable.');
  if(raw.state==='pending'&&raw.mediaId===undefined)return null;
  if(raw.state!=='ready'||raw.version!==1||!id(raw.mediaId,32)||!id(raw.motionId,64)
    ||typeof raw.avatarId!=='string'||raw.avatarId.length<1||raw.avatarId.length>256||raw.fps!==24
    ||!integer(raw.sourceFrameCount,1,1440)||!integer(raw.startFrame,0,raw.sourceFrameCount-1)
    ||!integer(raw.cursor,0,10000)||!Array.isArray(raw.segments)||raw.segments.length!==6)return invalid();
  const quality=parseVideoQuality(raw.videoQuality),count=raw.sourceFrameCount,start=raw.startFrame,media=raw.mediaId;
  let waitingPlan:IdleChunkWaitingPlan|undefined;
  if(raw.waitingPlan!==undefined||authority){
    const waiting=raw.waitingPlan;
    if(!authority||!object(waiting)||Object.keys(waiting).sort().join(',')!=='firstIndex,planId,sourceIndices,version'
      ||waiting.version!==1||!id(waiting.planId,32)||waiting.planId!==authority.planId
      ||!integer(waiting.firstIndex,0,10000)||waiting.firstIndex!==authority.firstIndex
      ||raw.avatarId!==authority.avatarId||count!==authority.sourceFrameCount
      ||!Array.isArray(waiting.sourceIndices)||waiting.sourceIndices.length<2||waiting.sourceIndices.length>1440
      ||waiting.sourceIndices.length!==authority.sourceIndices.length
      ||waiting.sourceIndices.some((frame:unknown,index:number)=>!integer(frame,0,count-1)||frame!==authority.sourceIndices[index]))return invalid();
    waitingPlan={version:1,planId:waiting.planId,firstIndex:waiting.firstIndex,sourceIndices:[...waiting.sourceIndices]};
  }
  const segments:IdleChunkRow[]=raw.segments.map((row:unknown,offset:number)=>{
    const index=raw.cursor+offset;
    if(!object(row)||row.index!==index||row.startFrame!==index*12||row.frameCount!==12
      ||!Array.isArray(row.sourceIndices)||row.sourceIndices.length!==12
      ||row.sourceIndices.some((frame:unknown,tick:number)=>frame!==(waitingPlan&&index>=waitingPlan.firstIndex
        ?waitingPlan.sourceIndices[((index-waitingPlan.firstIndex)*12+tick)%waitingPlan.sourceIndices.length]
        :(start+index*12+tick)%count))
      ||!['ready','pending'].includes(row.state))return invalid();
    if(row.state==='ready'&&(row.uri!==`/api/dev/musetalk-live/idle-chunk/${media}/${String(index).padStart(8,'0')}.mp4`
      ||!integer(row.bytes,1,16*1024*1024)||!id(row.sha256,64)))return invalid();
    if(row.state==='pending'&&['uri','bytes','sha256'].some(key=>row[key]!==undefined))return invalid();
    return {index,startFrame:index*12,frameCount:12,sourceIndices:[...row.sourceIndices],state:row.state,
      ...(row.state==='ready'?{uri:row.uri,bytes:row.bytes,sha256:row.sha256}:{})};
  });
  return {trialId,requestId,version:1,mediaId:media,motionId:raw.motionId,avatarId:raw.avatarId,
    sourceFrameCount:count,fps:24,startFrame:start,cursor:raw.cursor,videoQuality:quality,segments,...(waitingPlan?{waitingPlan}:{})};
}
