import {requireOptionalNativeModule} from 'expo';
import type {AudioPlayer} from 'expo-audio';

export type OrderedClockScope={version:1;ticket:string;run:{id:string;revision:number};streamId:string;generation:number};
export type OrderedClockObservation={known:boolean;sourceId:string|null;replyId:string|null;sequenceIndex:number|null;
  seconds:number|null;userPaused:boolean;playing:boolean;buffering:boolean;sampledAtMs:number};
type Player=AudioPlayer&{ncReadOrderedPlaybackClock?(scope:OrderedClockScope):Promise<unknown>};

/** Observation only, from OS-consumed samples attributed to one immutable speech source. */
export async function readOrderedPlaybackClock(player:AudioPlayer,scope:OrderedClockScope):Promise<OrderedClockObservation|null>{
  const native=requireOptionalNativeModule<{ncOrderedPlaybackClockVersion?():number}>('ExpoAudio');
  const ordered=player as Player;
  if(native?.ncOrderedPlaybackClockVersion?.()!==1||!ordered.ncReadOrderedPlaybackClock)return null;
  const sampledAtMs=performance.now();
  const value=await ordered.ncReadOrderedPlaybackClock(scope) as Record<string,unknown>;
  const run=value?.run as Record<string,unknown>|undefined;
  if(value?.version!==1||run?.id!==scope.run.id||run.revision!==scope.run.revision
    ||value.streamId!==scope.streamId||value.generation!==scope.generation
    ||typeof value.known!=='boolean'||typeof value.userPaused!=='boolean'
    ||typeof value.playing!=='boolean'||typeof value.buffering!=='boolean')return null;
  if(value.known){
    if(typeof value.sourceId!=='string'||!value.sourceId||typeof value.replyId!=='string'||!value.replyId
      ||!Number.isSafeInteger(value.sequenceIndex)||Number(value.sequenceIndex)<0
      ||typeof value.seconds!=='number'||!Number.isFinite(value.seconds)||value.seconds<0)return null;
  }else if(value.sourceId!==null||value.replyId!==null||value.sequenceIndex!==null||value.seconds!==null)return null;
  return {known:value.known,sourceId:value.sourceId as string|null,replyId:value.replyId as string|null,
    sequenceIndex:value.sequenceIndex as number|null,seconds:value.seconds as number|null,
    userPaused:value.userPaused,playing:value.playing,buffering:value.buffering,sampledAtMs};
}
