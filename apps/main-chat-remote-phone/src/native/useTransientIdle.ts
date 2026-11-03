import React from 'react';
import type {RemoteClient} from '../api/client';
import type {BufferedPresentation} from './bufferedPresentation';
import type {MuseTalkLiveTrial} from '../dev/museTalkLiveTrial';
import {parseArmedIdleStatus} from '../dev/museTalkLiveTrial';
import {peerMedia,isPeerMediaUrl} from '../relay/media';
import {downloadIdleFile} from '../dev/museTalkIdleFile';
import type {IdleFile} from '../dev/museTalkIdleFile';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';

/** Cache-off still needs its active silent loop. Reuse the ordinary producer
 * file, temporary-copy ownership and native idle decoder; never populate the
 * persistent avatar inventory or grant audio permission. */
export function useTransientIdle(client:RemoteClient,output:BufferedPresentation,trial:MuseTalkLiveTrial,enabled:boolean){
  const latest=React.useRef(client);latest.current=client;
  React.useEffect(()=>{
    if(!enabled)return;
    const abort=new AbortController(),files=new Map<string,{file:IdleFile;bytes:number}>();
    let pending:Promise<void>|null=null,selected='',failed=false;
    const live=(id:string)=>!abort.signal.aborted&&output.presentationActive&&trial.snapshot.phase==='armed'
      &&trial.snapshot.trialId===id&&!output.idleBusy;
    const tick=()=>{
      const id=trial.snapshot.trialId;
      if(pending||!live(id))return;
      const work=(async()=>{
        const peer=latest.current.bufferedPeer;if(!peer||peer.closed)return;
        const raw=await latest.current.requestLiveVisual('GET',`/api/dev/musetalk-live/status/${id}`,undefined,abort.signal);
        if(!live(id))return;
        const idle=parseArmedIdleStatus(raw,id);
        const metadata=raw as {motionId?:string;loopFadeMs?:number};
        if(!idle?.avatarId||!metadata.motionId||!/^[a-f0-9]{64}$/.test(metadata.motionId))return;
        const generation=JSON.stringify([peer.cacheScope,idle.avatarId,output.videoQuality]);
        const key=JSON.stringify([generation,metadata.motionId]);
        if(key===selected)return;
        let stored=files.get(key);
        if(!stored){
          const bytes=Array.from(files.values()).reduce((sum,row)=>sum+row.bytes,0);
          if(files.size>=96||bytes+idle.bytes>192*1024*1024)throw Error('Temporary idle capacity reached.');
          const resolved=await peerMedia(peer,idle.uri,{},abort.signal);if(!live(id))return;
          const file=await downloadIdleFile(resolved.url,idle.bytes,abort.signal,uri=>isPeerMediaUrl(peer,uri));
          if(abort.signal.aborted){file.release();return;}
          stored={file,bytes:idle.bytes};files.set(key,stored);
        }
        if(!live(id))return;
        const fade=metadata.loopFadeMs;
        if(!Number.isSafeInteger(fade)||fade!<0||fade!>5000)throw Error('Invalid temporary idle fade.');
        if(await output.prepareTransientIdle({uri:stored.file.uri,generation,id:metadata.motionId,fadeMs:fade!,
          source:{avatar_id:idle.avatarId,motion_id:metadata.motionId,source_frame_count:idle.frameCount}})){
          selected=key;failed=false;
        }
      })().catch(()=>{
        if(!abort.signal.aborted&&!failed){failed=true;void recordPhoneDebug('warning','buffered_active_idle_unavailable',{}).catch(()=>undefined);}
      }).finally(()=>{if(pending===work)pending=null;});
      pending=work;
    };
    tick();const timer=setInterval(tick,1000);
    return()=>{
      abort.abort();clearInterval(timer);
      // A superseded native prepare can still own its file. Fence it as well as
      // the active/fading readers before releasing any temporary copies.
      void (async()=>{await pending;await output.clearIdle();for(const row of files.values())row.file.release();files.clear();})()
        .catch(()=>{void recordPhoneDebug('warning','buffered_active_idle_detach_failed',{}).catch(()=>undefined);});
    };
  },[output,trial,enabled]);
}
