import {useEffect} from 'react';
import {requireNativeModule} from 'expo-modules-core';
import {Platform} from 'react-native';
import {createPolicyControl} from './policyControl';
import type {PolicyNative} from './policyControl';
import {recordDiagnosticEvent} from './phoneSink';

export function useDiagnosticPolicy(client:{diagnosticPolicy:()=>Promise<{policy:unknown}>},connected:boolean):void{
  useEffect(()=>{
    if(!connected)return;
    let native:PolicyNative|null=null;
    if(Platform.OS==='android')try{native=requireNativeModule<PolicyNative>('ExpoAudio');}catch{}
    const control=createPolicyControl(native,recordDiagnosticEvent);
    let stopped=false,busy=false;
    const tick=async()=>{
      if(stopped||busy)return;busy=true;
      try{const response=await client.diagnosticPolicy();if(!stopped)await control.apply(response.policy);}
      catch{if(!stopped)control.notice('unavailable','transport_failed');}
      finally{busy=false;}
    };
    void tick();const timer=setInterval(()=>{void tick();},5000);
    return()=>{stopped=true;clearInterval(timer);};
  },[client,connected]);
}
