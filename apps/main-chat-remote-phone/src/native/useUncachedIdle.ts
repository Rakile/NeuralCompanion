import React from 'react';
import type {RemoteClient} from '../api/client';
import type {MuseTalkLiveSession} from '../dev/museTalkLiveSession';
import type {BufferedPresentation} from './bufferedPresentation';
import type {BufferedPlaybackRuntime} from './bufferedPlaybackRuntime';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';

// Exact local messages only: never forward native/transport exception text.
function failureReason(error:unknown):string {
  const message=error&&typeof error==='object'?(error as {message?:unknown}).message:null;
  switch(message){
    case 'Idle chunk native prepare/append unavailable.':return 'native_prepare';
    case 'Idle chunk native selection unavailable.':return 'native_select';
    case 'Invalid idle chunk native file.':return 'native_file';
    case 'Invalid idle chunk status.':return 'protocol_status';
    case 'Idle chunk producer unavailable.':return 'producer_unavailable';
    case 'Invalid armed idle chunk source.':return 'armed_source';
    case 'Invalid armed idle chunk motion.':return 'armed_motion';
    case 'Invalid idle chunk cursor acknowledgement.':return 'cursor_ack';
    case 'Invalid idle decoder release cursor.':return 'decoder_cursor';
    case 'Buffered media descriptor length or content type mismatch.':return 'file_descriptor';
    case 'Peer media unavailable.':return 'file_transfer';
    case 'Live visual request failed.':return 'control_rejected';
    case 'Live visual peer route unavailable.':return 'peer_route';
    case 'Invalid live visual status.':return 'control_response';
    case 'NC peer request timed out.':return 'peer_timeout';
    case 'Internet peer is busy or disconnected.':return 'peer_busy';
    default:return 'transport_or_native';
  }
}

/** Delivery polling only: the desktop pre-renders complete files and native
 * consumption drives retirement. This timer never creates live video frames. */
export function useUncachedIdle(client:RemoteClient,output:BufferedPresentation,session:MuseTalkLiveSession,
  runtime:BufferedPlaybackRuntime,enabled:boolean){
  const latest=React.useRef(client);latest.current=client;
  const detached=React.useRef<Promise<void>>(Promise.resolve());
  React.useEffect(()=>{
    if(!enabled)return;
    if(!output.idleChunksSupported){
      void recordPhoneDebug('warning','idle_chunks_native_update_required',{}).catch(()=>undefined);return;
    }
    let active=true,work:Promise<void>|null=null,lastFailure='';
    let owner:ReturnType<BufferedPlaybackRuntime['startIdleChunks']>|null=null,scope='';
    const stop=()=>{
      const previous=owner;owner=null;scope='';
      if(previous)detached.current=previous.close();
      return detached.current;
    };
    const tick=()=>{
      if(!active||work)return;
      const pending=(async()=>{
        const peer=latest.current.bufferedPeer;
        if(owner&&peer&&peer.cacheScope!==scope)await stop();
        if(!owner){
          await detached.current;
          if(!active||!peer||peer.closed||!peer.cacheScope)return;
          owner=runtime.startIdleChunks(session,output);scope=peer.cacheScope;
        }
        if(active){await owner.tick();lastFailure='';}
      })().catch(error=>{
        if(!active)return;
        // No identifiers, credentials, paths or chat content in diagnostics.
        const stage=owner?'delivery':'detach_or_start';
        const reason=failureReason(error);
        const status=error&&typeof error==='object'?(error as {httpStatus?:unknown}).httpStatus:null;
        const httpStatus=Number.isInteger(status)&&Number(status)>=100&&Number(status)<=599?Number(status):null;
        const key=stage+':'+reason+':'+httpStatus;
        if(key!==lastFailure){lastFailure=key;
          void recordPhoneDebug('warning','idle_chunks_unavailable',{stage,reason,...(httpStatus===null?{}:{httpStatus})}).catch(()=>undefined);
        }
      }).finally(()=>{if(work===pending)work=null;});
      work=pending;
    };
    tick();const timer=setInterval(tick,100);
    return()=>{
      active=false;clearInterval(timer);
      void stop().catch(()=>{
        void recordPhoneDebug('warning','idle_chunks_detach_failed',{}).catch(()=>undefined);
      });
    };
  },[output,session,runtime,enabled]);
}
