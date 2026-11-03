import {AppRegistry,Platform} from 'react-native';
import {requireOptionalNativeModule} from 'expo';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';

type State={ticket?:string|null;playerId?:string|null;generation?:number|null;ready:boolean;reason?:string|null};
type Native={beginPlaybackBackground(ticket:string,playerId:string):Promise<State>;
  endPlaybackBackground(ticket:string,generation:number):Promise<void>;
  addListener(event:string,listener:(state:State)=>void):{remove():void}};
export type PlaybackBackgroundLease={close():Promise<void>};

/** Registered at app entry before native service admission. The native owner
 * settles this lifetime; no JS timer, capture, send, or duplicate pump lives here. */
export function registerAndroidPlaybackBackgroundTask():void{
  if(Platform.OS!=='android')return;
  AppRegistry.registerHeadlessTask('NCOrderedPlayback',()=>async(data:{ticket:string;generation:number})=>{
    const native=requireOptionalNativeModule<{awaitPlaybackBackgroundEnd(ticket:string,generation:number):Promise<boolean>}>('NcLiveCapture');
    if(!native?.awaitPlaybackBackgroundEnd)return;
    // Completion (including module shutdown) releases RN scheduling. The native
    // service detects unexpected completion and retires only its exact owner.
    await native.awaitPlaybackBackgroundEnd(data.ticket,data.generation).catch(()=>undefined);
  });
}
export async function beginAndroidPlaybackBackground(ticket:string,playerId:string,
  changed:(ready:boolean)=>void):Promise<PlaybackBackgroundLease|undefined>{
  if(Platform.OS!=='android')return;
  const native=requireOptionalNativeModule<Native>('NcLiveCapture');
  if(!native?.beginPlaybackBackground||!native.endPlaybackBackground)return;
  let generation:number|undefined,closed=false,latest:State|undefined;
  const subscription=native.addListener('playbackBackgroundEvent',state=>{
    latest=state;
    if(closed||generation===undefined)return;
    changed(state.ready&&state.ticket===ticket&&state.playerId===playerId&&state.generation===generation);
    void recordPhoneDebug('info','playback_background_state',{ready:state.ready,reason:state.reason??'none',generation});
  });
  try{
    const state=await native.beginPlaybackBackground(ticket,playerId);
    if(!state.ready||!Number.isSafeInteger(state.generation)||Number(state.generation)<=0){
      subscription.remove();changed(false);
      void recordPhoneDebug('info','playback_background_unavailable',{reason:state.reason??'confirmation_missing'});return;
    }
    generation=state.generation!;
    const observed=latest??state;
    changed(observed.ready&&observed.ticket===ticket&&observed.playerId===playerId&&observed.generation===generation);
    let closing:Promise<void>|undefined;
    return {close:()=>closing??=(async()=>{
      closed=true;changed(false);subscription.remove();await native.endPlaybackBackground(ticket,generation!);
    })()};
  }catch(error){subscription.remove();changed(false);throw error;}
}
