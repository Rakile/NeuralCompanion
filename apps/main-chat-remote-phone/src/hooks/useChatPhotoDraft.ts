import React from 'react';
import {Platform} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import {normalizePickedPhotoAsset, type ChatPhoto} from '../utils/chatPhoto';
import {remoteActionError} from '../api/envelope';

export type ChatPhotoDraft = ReturnType<typeof useChatPhotoDraft>;

/** One in-memory attachment shared by every chat view. Picking never submits. */
export function useChatPhotoDraft(identityKey: string, actions: {
  sendText: (text: string) => Promise<unknown>;
  sendImage: (photo: ChatPhoto, prompt: string) => Promise<unknown>;
}) {
  const [,render] = React.useState(0);
  const [error,setError] = React.useState('');
  const photo = React.useRef<ChatPhoto|null>(null);
  const generation = React.useRef(0), alive = React.useRef(true);
  const job = React.useRef<symbol|null>(null);
  const current = React.useRef(identityKey); current.current=identityKey;
  const refresh = () => { if(alive.current)render(n=>n+1); };
  const clear = React.useCallback(()=>{
    generation.current++;photo.current=null;job.current=null;setError('');refresh();
  },[]);
  React.useEffect(()=>{clear();},[identityKey,clear]);
  React.useEffect(()=>{alive.current=true;return()=>{alive.current=false;generation.current++;};},[]);

  const pick = async (source: 'camera'|'gallery') => {
    if(job.current)return;
    const token=Symbol(),epoch=generation.current,owner=identityKey;
    job.current=token;setError('');refresh();
    const valid=()=>alive.current&&epoch===generation.current&&owner===current.current;
    try {
      const permission=source==='camera'?await ImagePicker.requestCameraPermissionsAsync():await ImagePicker.requestMediaLibraryPermissionsAsync();
      if(!valid())return;
      if(!permission.granted)throw Error(`${source==='camera'?'Camera':'Photo library'} permission is required.`);
      const options: ImagePicker.ImagePickerOptions={mediaTypes:['images'],allowsEditing:false,base64:true,quality:.82,
        ...(Platform.OS==='ios'?{preferredAssetRepresentationMode:ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible}:{})};
      const result=source==='camera'?await ImagePicker.launchCameraAsync(options):await ImagePicker.launchImageLibraryAsync(options);
      if(!valid()||result.canceled)return;
      const selected=normalizePickedPhotoAsset(result.assets?.[0]??{});
      if(!selected)throw Error('The image could not be read.');
      photo.current={...selected,source};refresh();
    }catch(failure){if(valid())setError(failure instanceof Error?failure.message:'Could not attach photo.');}
    finally{if(job.current===token){job.current=null;refresh();}}
  };
  const submit = async (text:string,selected:ChatPhoto|null,epoch:number,owner:string,
    sendImage=actions.sendImage) => {
    if(!alive.current||epoch!==generation.current||owner!==current.current||selected!==photo.current)throw Error('The photo or conversation changed. Please try again.');
    if(job.current)throw Error('A photo action is already in progress.');
    const message=text.trim();if(!selected&&!message)return;
    // Keep ordinary text submission and its captured authority unchanged.
    if(!selected){await actions.sendText(message);return;}
    const token=Symbol();job.current=token;setError('');refresh();
    try{
      const response=await sendImage(selected,message||'Please respond to this photo.');
      const failure=remoteActionError(response,'Message was not accepted.');if(failure)throw Error(failure);
      if(alive.current&&epoch===generation.current&&owner===current.current&&photo.current===selected){photo.current=null;refresh();}
    }finally{if(job.current===token){job.current=null;refresh();}}
  };
  const send=(text:string)=>submit(text,photo.current,generation.current,identityKey);
  const prepareVoiceSubmission=(sendImage?:typeof actions.sendImage)=>{
    const selected=photo.current,epoch=generation.current,owner=identityKey;
    return selected?(text:string)=>submit(text,selected,epoch,owner,sendImage):undefined;
  };
  return {photo:photo.current,busy:job.current!==null,error,pick,clear,send,prepareVoiceSubmission};
}
