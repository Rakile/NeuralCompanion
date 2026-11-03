import {Platform} from 'react-native';

export function playCharacterAddedSound():void {
  if(Platform.OS!=='android')return;
  try {
    const {requireOptionalNativeModule}=require('expo-modules-core') as typeof import('expo-modules-core');
    const native=requireOptionalNativeModule<{playCharacterAddedSound?:()=>Promise<boolean>}>('NcLiveCapture');
    void native?.playCharacterAddedSound?.().catch(()=>undefined);
  } catch { /* Older APKs do not expose the optional sound capability. */ }
}
