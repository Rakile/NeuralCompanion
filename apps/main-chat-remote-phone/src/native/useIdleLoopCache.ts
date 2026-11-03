import React from 'react';
import type {RemoteClient} from '../api/client';
import {IdleLoopSession} from '../relay/idleLoopSession';
import type {IdlePresentation} from '../relay/idleLoopSession';
import type {PhonePresentationPosition,HandoffExchange} from '../utils/phonePresentation';
import {phoneIdleCache,setIdleSession,publishIdleStatus,detachIdleSession} from './idleCacheRuntime';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import {registerPhonePositionReader,registerPhoneHandoff} from '../utils/phonePresentation';

export type IdleCachePresentation=IdlePresentation & {
  readonly presentationActive:boolean;readonly idleClockSupported:boolean;
  readIdlePosition():PhonePresentationPosition|null;handoffExchange():HandoffExchange|null;
};
export function useIdleLoopCache(client:RemoteClient,output:IdleCachePresentation,enabled:boolean,
  options:{freezeEnabled?:boolean;revision?:number}={}){
  const latest=React.useRef(client);latest.current=client;
  const revision=options.revision??0,freezeEnabled=options.freezeEnabled===true;
  const [mode,setMode]=React.useState<{revision:number;enabled:boolean}|null>(null);
  React.useEffect(()=>{
    if(!enabled||!output.idleClockSupported)return;
    const position=registerPhonePositionReader(client,()=>output.readIdlePosition());
    const handoff=registerPhoneHandoff(client,()=>output.handoffExchange());
    return()=>{position();handoff();};
  },[client,output,enabled]);
  React.useEffect(()=>{
    if(!enabled)return;
    const cache=phoneIdleCache();if(!cache)return;
    // Connection credentials can rotate/peers can be replaced without changing
    // the authenticated presentation owner supplied by the app.
    const current=new Proxy({} as RemoteClient,{get:(_target,key)=>{
      const value=Reflect.get(latest.current,key);
      return typeof value==='function'?value.bind(latest.current):value;
    }});
    const session=new IdleLoopSession(current,output,cache);setIdleSession(session);
    const abort=new AbortController();let busy=false,lastReason='',lastFailure='',lastEnabled:boolean|null=null;
    const tick=async()=>{
      if(busy || abort.signal.aborted)return;busy=true;
      let stage='support';
      try{
        // Frozen cache-off relinquished the native surface once. Further
        // settings IO (including failure) cannot revoke the chunk owner.
        if(freezeEnabled&&lastEnabled===false){session.status.reason='disabled';return;}
        if(!output.idleSupported){session.status.reason='native_update_required';return;}
        if(current.bufferedPeer?.closed || current.avTransportClosed){session.status.reason='reconnecting';return;}
        stage='settings';
        const settings=await current.idleCacheSettings(abort.signal);if(abort.signal.aborted)return;
        if(freezeEnabled&&lastEnabled===true&&!settings.enabled){
          session.status.reason='mode_reconnect_required';return;
        }
        // Buffered cache-off and cache-on are distinct visual owners. As the
        // desktop instructions state, a changed mode applies on reconnect;
        // never tear down an admitted speech transition from a settings poll.
        const selectedEnabled=freezeEnabled&&lastEnabled!==null?lastEnabled:settings.enabled;
        if(!selectedEnabled){
          if(lastEnabled!==false)session.pause();
          lastEnabled=false;setMode({revision,enabled:false});session.status.reason='disabled';return;
        }
        lastEnabled=true;setMode({revision,enabled:true});
        if(!output.presentationActive){session.pause();return;}
        stage='manifest';
        const manifest=await current.idleCacheManifest(abort.signal,output.idleClockSupported);if(abort.signal.aborted)return;
        stage='update';
        if(manifest)await session.update(manifest,settings.clear_generation);
        else {session.pause();session.status.reason='catalog_pending';}
        lastFailure='';
      }catch{if(!abort.signal.aborted){
        if(current.bufferedPeer?.closed || current.avTransportClosed){session.status.reason='reconnecting';return;}
        if(!freezeEnabled||!output.idleBusy)session.pause();
        session.status.reason='streamed_fallback';
        if(lastFailure!==stage){lastFailure=stage;
          void recordPhoneDebug('warning','idle_cache_failure',{stage}).catch(()=>undefined);
        }
      }}
      finally{
        busy=false;
        if(!abort.signal.aborted){
          publishIdleStatus(session,session.status);
          const signature=JSON.stringify([session.status.reason,session.status.files,session.status.complete,session.status.failureStage]);
          if(lastReason!==signature){lastReason=signature;
            void recordPhoneDebug('info','idle_cache_state',{reason:session.status.reason,files:session.status.files,
              bytes:session.status.bytes,complete:session.status.complete,
              stage:session.status.failureStage}).catch(()=>undefined);
          }
        }
      }
    };
    void tick();const timer=setInterval(()=>{void tick();},2000);
    return()=>{abort.abort();clearInterval(timer);detachIdleSession(session);};
  },[output,enabled,freezeEnabled,revision]);
  return mode?.revision===revision?mode.enabled:null;
}
