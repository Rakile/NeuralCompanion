import {parseIdleChunkStatus} from '../dev/idleChunkProtocol';
import {parseSourceTimeline} from '../relay/frameHandoff';
import type {SourceTimeline} from '../relay/frameHandoff';
import type {IdleChunkRetainedWindow} from './idleChunkQueue';
import type {BufferedVisualSource} from './bufferedHandoff';
import type {NativeIdleChunkFile} from './idleChunkNativeReader';
import {isIdleChunkFileUri} from './idleChunkNativeReader';

const id=(value:unknown,length:number)=>typeof value==='string'&&new RegExp(`^[a-f0-9]{${length}}$`).test(value);
/** Validate all six retained files against the final declared speech mapping.
 * This is a prospective silent return, not permission to select or play it. */
export function validateChunkVisualSource(source:BufferedVisualSource,value:SourceTimeline):void {
  const timeline=parseSourceTimeline(value),chunks=source.idleChunks;
  const invalid=()=>{throw Error('Invalid buffered chunk return source.');};
  if(!chunks||Object.keys(chunks).sort().join(',')!=='files,mediaId'||!id(chunks.mediaId,32)
    ||!id(source.idleGeneration,32)||!id(source.idleSha,64)||source.idleId!==timeline.motionId
    ||source.motionId!==timeline.motionId||source.sourceFrameCount!==timeline.sourceFrameCount
    ||JSON.stringify(source.sourceIndices)!==JSON.stringify(timeline.sourceIndices)
    ||source.startFrame!==(timeline.sourceIndices.at(-1)!+1)%timeline.sourceFrameCount
    ||!Number.isSafeInteger(source.fadeMs)||source.fadeMs<0||source.fadeMs>5000
    ||!Array.isArray(chunks.files)||chunks.files.length!==6)return invalid();
  const paths=new Set<string>();
  for(let index=0;index<6;index++){
    const file=chunks.files[index];
    if(!file||file.generation!==source.idleGeneration||file.motionId!==source.motionId||file.mediaId!==chunks.mediaId
      ||file.sourceFrameCount!==source.sourceFrameCount||file.startFrame!==source.startFrame||file.index!==index
      ||file.fadeMs!==source.fadeMs||!id(file.sha256,64)||!isIdleChunkFileUri(file.uri)||paths.has(file.uri)
      ||!Array.isArray(file.sourceIndices)||file.sourceIndices.length!==12
      ||file.sourceIndices.some((frame,tick)=>frame!==(source.startFrame+index*12+tick)%source.sourceFrameCount))return invalid();
    paths.add(file.uri);
  }
  const first=chunks.files[0];
  if(!first||source.idleUri!==first.uri||source.idleSha!==first.sha256)return invalid();
}
export function makeChunkVisualSource(window:IdleChunkRetainedWindow,value:SourceTimeline,fadeMs:number):BufferedVisualSource {
  const timeline=parseSourceTimeline(value),raw=window.status;
  const status=parseIdleChunkStatus({...raw,state:'ready'},raw.trialId,raw.requestId);
  if(!status||status.cursor!==0||window.files.length!==6)throw Error('Buffered chunk return lookahead missing.');
  const files:NativeIdleChunkFile[]=window.files.map(({row,uri},index)=>{
    const segment=status.segments[index];
    if(!segment||row.index!==index||row.state!=='ready'||segment.state!=='ready'||segment.startFrame!==row.startFrame
      ||segment.frameCount!==row.frameCount||segment.uri!==row.uri||segment.bytes!==row.bytes||segment.sha256!==row.sha256
      ||JSON.stringify(segment.sourceIndices)!==JSON.stringify(row.sourceIndices))throw Error('Buffered chunk return row changed.');
    return {generation:status.trialId,motionId:status.motionId,mediaId:status.mediaId,uri,sha256:row.sha256!,
      sourceFrameCount:status.sourceFrameCount,startFrame:status.startFrame,index,sourceIndices:[...row.sourceIndices],fadeMs};
  });
  const first=files[0];if(!first)throw Error('Buffered chunk return lookahead missing.');
  const source:BufferedVisualSource={motionId:status.motionId,sourceFrameCount:status.sourceFrameCount,
    sourceIndices:[...timeline.sourceIndices],idleGeneration:status.trialId,idleId:status.motionId,
    idleUri:first.uri,idleSha:first.sha256,startFrame:status.startFrame,fadeMs,idleChunks:{mediaId:status.mediaId,files}};
  validateChunkVisualSource(source,timeline);return source;
}
