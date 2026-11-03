import {Platform} from 'react-native';
import {requireOptionalNativeModule} from 'expo';

type Native = {
  beginPeerConnectionBackground(ticket:string):Promise<boolean>;
  endPeerConnectionBackground(ticket:string):Promise<void>;
  addListener(event:string,listener:(event:{ticket:string})=>void):{remove():void};
};
export type PeerBackgroundLease={close():Promise<void>};

export async function beginPeerConnectionBackground(stopped:()=>void):Promise<PeerBackgroundLease|undefined> {
  if(Platform.OS!=='android')return;
  const native=requireOptionalNativeModule<Native>('NcLiveCapture');
  if(!native?.beginPeerConnectionBackground)return;
  const ticket=`peer-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const subscription=native.addListener('peerConnectionStopped',event=>{if(event.ticket===ticket)stopped();});
  try {
    if(!await native.beginPeerConnectionBackground(ticket))throw new Error('Could not keep the desktop connection active in the background. Return to NC and reconnect Internet.');
  } catch(error) {
    subscription.remove();await native.endPeerConnectionBackground(ticket).catch(()=>undefined);throw error;
  }
  let closing:Promise<void>|undefined;
  return {close:()=>closing??=(async()=>{subscription.remove();await native.endPeerConnectionBackground(ticket);})()};
}
