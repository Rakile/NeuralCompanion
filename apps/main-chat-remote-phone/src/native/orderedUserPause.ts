import {requireOptionalNativeModule} from 'expo';
import type {AudioPlayer} from 'expo-audio';

type Native={ncOrderedUserPauseVersion?():number};
type Player=AudioPlayer&{ncSetOrderedUserPaused?(ticket:string,paused:boolean):Promise<boolean>};

/** Native confirms a barrier on the exact carrier; ordinary controls are never a fallback. */
export async function setOrderedUserPaused(player:AudioPlayer,ticket:string,paused:boolean):Promise<void>{
  const native=requireOptionalNativeModule<Native>('ExpoAudio'),ordered=player as Player;
  if(native?.ncOrderedUserPauseVersion?.()!==1||!ordered.ncSetOrderedUserPaused)
    throw Error('Update NC Remote to pause ordered playback.');
  if(await ordered.ncSetOrderedUserPaused(ticket,paused)!==true)
    throw Error('Ordered playback ownership changed. Try again.');
}
