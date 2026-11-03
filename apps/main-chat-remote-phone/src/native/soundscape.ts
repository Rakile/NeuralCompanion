import {requireOptionalNativeModule} from 'expo';
import {Platform} from 'react-native';
import type {SoundscapeScope} from '../api/soundscape';

type Payload = Record<string, unknown>;
type Module = {
  ncSoundscapeVersion(): number;
  ncSoundscapeEffectVersion?(): number;
  ncSoundscapeEffect?(payload:Payload):Promise<boolean>;
  ncSoundscapeStopEffect?(payload:Payload):Promise<void>;
  ncSoundscapeBeginLoad(payload:Payload): Promise<number>;
  ncSoundscapeApply(payload:Payload): Promise<boolean>;
  ncSoundscapeResume(payload:Payload): Promise<boolean>;
  ncSoundscapePreview(payload:Payload): Promise<boolean>;
  ncSoundscapeStopPreview(payload:Payload): Promise<void>;
  ncSoundscapePreviewPlaying?(payload:Payload): Promise<boolean>;
  ncSoundscapePause(payload:Payload): Promise<void>;
  ncSoundscapeClose(payload:Payload): Promise<void>;
  ncSoundscapeSpeech(payload:Payload): Promise<void>;
  ncSoundscapeDuck(payload:Payload): Promise<void>;
  ncSoundscapeFileBegin(scope:string, hash:string, bytes:number): Promise<{token:string;ready:boolean}>;
  ncSoundscapeFileWrite(token:string, offset:number, data:string): Promise<boolean>;
  ncSoundscapeFileFinish(token:string): Promise<boolean>;
  ncSoundscapeFileForget(token:string): Promise<boolean>;
  ncSoundscapeImportInfo(uri:string): Promise<{sha256:string;byte_length:number}>;
  ncSoundscapeImportRead(uri:string, offset:number, length:number): Promise<{data:string;sha256:string}>;
  addListener(event:string, listener:(event:Payload)=>void): {remove():void};
};
function module(): Module | null {
  if(Platform.OS!=='android') return null;
  try { const value=requireOptionalNativeModule<Module>('ExpoAudio'); return value?.ncSoundscapeVersion?.()===1 ? value : null; }
  catch {return null;}
}
function required(): Module { const value=module(); if(!value)throw new Error('Soundscape requires the updated Android app.'); return value; }
export const soundscapeNative = {
  available:()=>module()!==null,
  effectsAvailable:()=>module()?.ncSoundscapeEffectVersion?.()===1,
  effect:async(payload:Payload)=>await required().ncSoundscapeEffect?.(payload)??false,
  stopEffect:async(scope:SoundscapeScope)=>{await module()?.ncSoundscapeStopEffect?.({scope});},
  begin:(scope:SoundscapeScope,layer:string)=>required().ncSoundscapeBeginLoad({scope,layer}),
  apply:(payload:Payload)=>required().ncSoundscapeApply(payload),
  resume:(scope:SoundscapeScope)=>required().ncSoundscapeResume({scope}),
  pause:(scope:SoundscapeScope,reason:string)=>required().ncSoundscapePause({scope,reason}),
  close:(scope:SoundscapeScope)=>required().ncSoundscapeClose({scope}),
  preview:(payload:Payload)=>required().ncSoundscapePreview(payload),
  stopPreview:(scope:SoundscapeScope)=>required().ncSoundscapeStopPreview({scope}),
  previewPlaying:async(scope:SoundscapeScope,playing:boolean)=>await required().ncSoundscapePreviewPlaying?.({scope,playing})??false,
  speech:(scope:SoundscapeScope,reply_id:string,audible:boolean,terminal:boolean)=>required().ncSoundscapeSpeech({scope,reply_id,audible,terminal}),
  duck:(scope:SoundscapeScope,enabled:boolean)=>required().ncSoundscapeDuck({scope,enabled}),
  subscribe:(listener:(event:Payload)=>void)=>module()?.addListener('soundscapeState',listener) ?? {remove(){}},
  fileBegin:(scope:string,hash:string,bytes:number)=>required().ncSoundscapeFileBegin(scope,hash,bytes),
  fileWrite:(token:string,offset:number,data:string)=>required().ncSoundscapeFileWrite(token,offset,data),
  fileFinish:(token:string)=>required().ncSoundscapeFileFinish(token),
  fileForget:(token:string)=>required().ncSoundscapeFileForget(token),
  importInfo:(uri:string)=>required().ncSoundscapeImportInfo(uri),
  importRead:(uri:string,offset:number,length:number)=>required().ncSoundscapeImportRead(uri,offset,length),
};
