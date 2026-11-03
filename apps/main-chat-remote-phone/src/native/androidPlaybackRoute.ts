import {Platform,PermissionsAndroid} from 'react-native';
import {requireOptionalNativeModule} from 'expo';

/** Initial output-only routing. Never asks for RECORD_AUDIO or opens capture. */
export async function prepareAndroidPlaybackRoute(ticket:string,current:()=>boolean):Promise<void>{
  if(Platform.OS!=='android'||Number(Platform.Version)<31||!current())return;
  const native=requireOptionalNativeModule<{ncPreparePlaybackRoute?(ticket:string):Promise<boolean>}>('ExpoAudio');
  if(typeof native?.ncPreparePlaybackRoute!=='function')return; // Older installed native builds.
  const permission=PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT;
  const granted=await PermissionsAndroid.check(permission)
    ||await PermissionsAndroid.request(permission)===PermissionsAndroid.RESULTS.GRANTED;
  if(!granted||!current())return;
  await native.ncPreparePlaybackRoute(ticket);
}
