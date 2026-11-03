/** Visual metadata is not a playback capability or proof of presentation. */
export type SourceTimeline = {version:1;motionId:string;sourceFrameCount:number;sourceFps:24;sourceIndices:number[]};
const integer=(value:unknown,low=0,high=Number.MAX_SAFE_INTEGER):value is number =>
  Number.isSafeInteger(value) && Number(value)>=low && Number(value)<=high;

export function parseSourceTimeline(value:unknown):SourceTimeline {
  if(!value || typeof value!=='object' || Array.isArray(value))throw Error('Invalid source timeline.');
  const v=value as Record<string,unknown>;
  if(Object.keys(v).sort().join(',')!=='motionId,sourceFps,sourceFrameCount,sourceIndices,version'
    || v.version!==1 || typeof v.motionId!=='string' || !/^[a-f0-9]{64}$/.test(v.motionId)
    || !integer(v.sourceFrameCount,1,1440) || v.sourceFps!==24 || !Array.isArray(v.sourceIndices)
    || v.sourceIndices.length<1 || v.sourceIndices.length>1440
    || v.sourceIndices.some(index=>!integer(index,0,Number(v.sourceFrameCount)-1)))throw Error('Invalid source timeline.');
  return {version:1,motionId:v.motionId,sourceFrameCount:v.sourceFrameCount,sourceFps:24,sourceIndices:[...v.sourceIndices]};
}

export function sourceFrame(timeline:SourceTimeline,sourceTick:number):number {
  const value=parseSourceTimeline(timeline);
  if(!integer(sourceTick,0,value.sourceIndices.length-1))throw Error('Source tick out of range.');
  return value.sourceIndices[sourceTick]!; // Validated integral index within the detached array.
}

/** Only confirmed clip-relative encoded PTS belongs here; never seek targets. */
export function presentedSourceFrame(timeline:SourceTimeline,pts:number,timescale:number):number {
  if(!integer(pts) || !integer(timescale,1))throw Error('Invalid presentation timestamp.');
  return sourceFrame(timeline,Number((BigInt(pts)*BigInt(48)+BigInt(timescale))/(BigInt(timescale)*BigInt(2))));
}
