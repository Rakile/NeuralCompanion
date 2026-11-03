import {useEffect} from 'react';
import {Platform} from 'react-native';
import {requireNativeModule} from 'expo-modules-core';
import {startNativeDiagnostics} from './nativeForwarder';
import type {NativeDiagnostics} from './nativeForwarder';
import {recordDiagnosticEvent} from './phoneSink';
import {recordPhoneDebug} from '../utils/phoneDebug';

export function useNativeDiagnostics():void{
  useEffect(()=>{
    if(Platform.OS!=='android')return;
    let native:NativeDiagnostics|null=null;
    try{native=requireNativeModule<NativeDiagnostics>('ExpoAudio');}catch{}
    return startNativeDiagnostics(native,recordDiagnosticEvent,reason=>{
      void recordPhoneDebug('warning','native_diagnostic_forwarding_failure',{reason}).catch(()=>undefined);
    });
  },[]);
}
